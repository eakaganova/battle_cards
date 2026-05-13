from __future__ import annotations

import io
import re
import time
from dataclasses import asdict
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .config import AppConfig
from .models import SourceArtifact


ProgressCallback = Callable[[str, str, str], None]


EXPAND_TEXT_RE = re.compile(
    r"показать|ещ[её]|подробнее|раскрыть|читать|more|show|expand|details|faq|условия",
    re.I,
)


def retry(operation: Callable[[], SourceArtifact], attempts: int, on_error: Callable[[str], None]) -> SourceArtifact:
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            on_error(f"Попытка {attempt}/{attempts} не удалась: {exc}")
            time.sleep(min(2 * attempt, 6))
    raise RuntimeError(str(last_error))


def fetch_source(
    competitor: str,
    url: str,
    manual_text: str,
    uploaded_text: str,
    config: AppConfig,
    progress: ProgressCallback,
) -> SourceArtifact:
    if manual_text.strip() or uploaded_text.strip():
        text = "\n\n".join(part for part in [manual_text.strip(), uploaded_text.strip()] if part)
        progress("manual", competitor, "Использую ручной источник вместо веб-парсинга.")
        return SourceArtifact(
            competitor=competitor,
            url=url,
            raw_text=text,
            cleaned_text=clean_text(text),
            extraction_method="manual_fallback",
            status="success",
        )
    if not url.strip():
        return SourceArtifact(
            competitor=competitor,
            url=url,
            status="failed",
            errors=["Не указан URL и не передан ручной текст."],
        )

    def operation() -> SourceArtifact:
        try:
            progress("playwright", competitor, "Открываю страницу, жду JS и раскрываю скрытые блоки.")
            return fetch_with_playwright(competitor, url, config, progress)
        except Exception as exc:
            progress("requests", competitor, f"Playwright недоступен или не справился: {exc}. Перехожу на fallback.")
            return fetch_with_requests(competitor, url, config)

    return retry(operation, config.max_retries, lambda message: progress("retry", competitor, message))


def fetch_with_requests(competitor: str, url: str, config: AppConfig) -> SourceArtifact:
    response = requests.get(
        url,
        timeout=config.request_timeout_seconds,
        headers={
            "User-Agent": "Mozilla/5.0 CompetitiveResearchBot/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    response.raise_for_status()
    try:
        soup = BeautifulSoup(response.text, "lxml")
    except Exception:
        soup = BeautifulSoup(response.text, "html.parser")
    return artifact_from_soup(competitor, url, response.text, soup, "requests_bs4")


def fetch_with_playwright(
    competitor: str,
    url: str,
    config: AppConfig,
    progress: ProgressCallback,
) -> SourceArtifact:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            user_agent="Mozilla/5.0 CompetitiveResearchBot/1.0",
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=config.playwright_timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                progress("dynamic", competitor, "Network idle не наступил, продолжаю с уже отрисованным DOM.")
            click_cookie_banners(page)
            scroll_deep(page, progress, competitor)
            clicked = click_expandable(page, progress, competitor)
            modal_texts = collect_modal_texts(page, progress, competitor)
            html = page.content()
            try:
                soup = BeautifulSoup(html, "lxml")
            except Exception:
                soup = BeautifulSoup(html, "html.parser")
            artifact = artifact_from_soup(competitor, url, html, soup, "playwright_deep")
            artifact.modal_texts = modal_texts
            artifact.hidden_text = collect_hidden_text(soup)
            if clicked:
                artifact.status = f"success_expanded_{clicked}_controls"
            return artifact
        finally:
            context.close()
            browser.close()


def click_cookie_banners(page) -> int:
    clicked = 0
    selectors = [
        "button:has-text('Принять')",
        "button:has-text('Согласен')",
        "button:has-text('Accept')",
        "button:has-text('OK')",
    ]
    for selector in selectors:
        try:
            elements = page.locator(selector)
            count = min(elements.count(), 3)
            for index in range(count):
                elements.nth(index).click(timeout=800)
                clicked += 1
        except Exception:
            pass
    return clicked


def scroll_deep(page, progress: ProgressCallback, competitor: str) -> None:
    previous_height = 0
    for _ in range(8):
        height = page.evaluate("document.body.scrollHeight")
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(650)
        if height == previous_height:
            break
        previous_height = height
    progress("dynamic", competitor, "Динамический контент досканирован прокруткой.")


def click_expandable(page, progress: ProgressCallback, competitor: str) -> int:
    clicked = 0
    candidates = page.locator("button, a, [role='button'], summary, [aria-expanded='false']")
    count = min(candidates.count(), 160)
    for index in range(count):
        try:
            element = candidates.nth(index)
            label = " ".join((element.inner_text(timeout=500) or element.get_attribute("aria-label") or "").split())
            if not label or not EXPAND_TEXT_RE.search(label):
                continue
            before_url = page.url
            element.click(timeout=900)
            page.wait_for_timeout(450)
            if page.url != before_url:
                page.go_back(wait_until="domcontentloaded", timeout=5000)
            clicked += 1
        except Exception:
            continue
    progress("accordion", competitor, f"Раскрыто интерактивных элементов: {clicked}.")
    return clicked


def collect_modal_texts(page, progress: ProgressCallback, competitor: str) -> List[str]:
    texts: List[str] = []
    for selector in ["[role='dialog']", ".modal", "[aria-modal='true']"]:
        try:
            locator = page.locator(selector)
            for index in range(min(locator.count(), 20)):
                text = clean_text(locator.nth(index).inner_text(timeout=500))
                if text and text not in texts:
                    texts.append(text)
        except Exception:
            pass
    if texts:
        progress("modals", competitor, f"Извлечено модальных окон: {len(texts)}.")
    return texts


def artifact_from_soup(competitor: str, url: str, html: str, soup: BeautifulSoup, method: str) -> SourceArtifact:
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    faq_items = extract_faq(soup)
    tables = extract_tables(soup)
    pdf_links = extract_document_links(soup, url)
    iframe_urls = [urljoin(url, item.get("src", "")) for item in soup.find_all("iframe") if item.get("src")]
    text_parts = [
        soup.get_text("\n", strip=True),
        format_faq(faq_items),
        format_tables(tables),
        collect_hidden_text(soup),
    ]
    raw_text = "\n\n".join(part for part in text_parts if part)
    return SourceArtifact(
        competitor=competitor,
        url=url,
        raw_html=html[:300000],
        raw_text=raw_text,
        cleaned_text=clean_text(raw_text),
        tables=tables,
        faq_items=faq_items,
        pdf_links=pdf_links,
        iframe_urls=iframe_urls,
        extraction_method=method,
        status="success",
    )


def extract_faq(soup: BeautifulSoup) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for item in soup.select("[itemscope], details, .faq, .accordion, [class*='faq'], [class*='question']"):
        text = clean_text(item.get_text("\n", strip=True))
        if "?" in text and len(text) > 20:
            parts = text.split("\n", 1)
            result.append({"question": parts[0][:300], "answer": parts[1][:1000] if len(parts) > 1 else text[:1000]})
    return result[:80]


def extract_tables(soup: BeautifulSoup) -> List[Dict[str, object]]:
    tables: List[Dict[str, object]] = []
    for table in soup.find_all("table")[:30]:
        rows = []
        for row in table.find_all("tr"):
            cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if rows:
            tables.append({"rows": rows[:80]})
    return tables


def extract_document_links(soup: BeautifulSoup, base_url: str) -> List[str]:
    links: List[str] = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        label = link.get_text(" ", strip=True)
        if re.search(r"\.(pdf|docx?|xlsx?|csv)(\?|$)", href, re.I) or re.search(r"pdf|документ|тариф|услов", label, re.I):
            absolute = urljoin(base_url, href)
            if absolute not in links:
                links.append(absolute)
    return links[:50]


def collect_hidden_text(soup: BeautifulSoup) -> str:
    texts: List[str] = []
    for item in soup.select("[hidden], [aria-hidden='true'], [style*='display:none'], [style*='display: none']"):
        text = clean_text(item.get_text(" ", strip=True))
        if text and len(text) > 20:
            texts.append(text)
    return "\n".join(texts[:80])


def format_faq(items: List[Dict[str, str]]) -> str:
    if not items:
        return ""
    return "\n".join(f"FAQ: {item['question']}\n{item['answer']}" for item in items)


def format_tables(tables: List[Dict[str, object]]) -> str:
    lines: List[str] = []
    for index, table in enumerate(tables, start=1):
        lines.append(f"TABLE {index}")
        for row in table.get("rows", []):
            lines.append(" | ".join(str(cell) for cell in row))
    return "\n".join(lines)


def clean_text(text: str) -> str:
    text = re.sub(r"\r", "\n", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def artifact_to_cache_value(artifact: SourceArtifact) -> Dict[str, object]:
    return asdict(artifact)
