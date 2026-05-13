from __future__ import annotations

import io
import json
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

TAB_TEXT_RE = re.compile(
    r"тариф|услов|документ|погашен|вопрос|ответ|требован|ставк|пск|комисс|страх|оформ|получ|faq|documents|tariff|terms",
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
        static_artifact: Optional[SourceArtifact] = None
        try:
            progress("requests", competitor, "Сначала читаю статический HTML: многие банковские страницы уже содержат условия в серверной разметке.")
            static_artifact = fetch_with_requests(competitor, url, config)
        except Exception as exc:
            progress("requests", competitor, f"Статический парсер не справился: {exc}. Продолжаю через браузер.")

        try:
            progress("playwright", competitor, "Открываю страницу, жду JS и раскрываю скрытые блоки.")
            browser_artifact = fetch_with_playwright(competitor, url, config, progress)
            if static_artifact:
                return merge_artifacts(static_artifact, browser_artifact)
            return browser_artifact
        except Exception as exc:
            progress("requests", competitor, f"Playwright недоступен или не справился: {exc}. Использую статический HTML, если он собран.")
            if static_artifact:
                static_artifact.errors.append(f"Playwright не сработал: {exc}")
                static_artifact.status = "partial_success_static_only"
                return static_artifact
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
    html_text = decode_response_text(response)
    try:
        soup = BeautifulSoup(html_text, "lxml")
    except Exception:
        soup = BeautifulSoup(html_text, "html.parser")
    return artifact_from_soup(competitor, url, html_text, soup, "requests_bs4")


def merge_artifacts(static_artifact: SourceArtifact, browser_artifact: SourceArtifact) -> SourceArtifact:
    merged_text = merge_text_blocks(
        [
            "=== СТАТИЧЕСКИЙ HTML ===\n" + static_artifact.raw_text,
            "=== БРАУЗЕРНЫЙ DOM ===\n" + browser_artifact.raw_text,
            "=== СКРЫТЫЙ ТЕКСТ ===\n" + browser_artifact.hidden_text,
            "=== МОДАЛЬНЫЕ ОКНА ===\n" + "\n\n".join(browser_artifact.modal_texts),
        ]
    )
    primary = browser_artifact if len(browser_artifact.raw_text) >= len(static_artifact.raw_text) else static_artifact
    primary.raw_text = merged_text
    primary.cleaned_text = clean_text(merged_text)
    primary.tables = static_artifact.tables + browser_artifact.tables
    primary.faq_items = static_artifact.faq_items + browser_artifact.faq_items
    primary.pdf_links = unique_list(static_artifact.pdf_links + browser_artifact.pdf_links)
    primary.iframe_urls = unique_list(static_artifact.iframe_urls + browser_artifact.iframe_urls)
    primary.errors = static_artifact.errors + browser_artifact.errors
    primary.extraction_method = f"{static_artifact.extraction_method}+{browser_artifact.extraction_method}"
    primary.status = "success_merged_static_and_browser"
    return primary


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
            tab_texts = click_tabs_and_collect_text(page, progress, competitor)
            modal_texts = collect_modal_texts(page, progress, competitor)
            html = page.content()
            try:
                soup = BeautifulSoup(html, "lxml")
            except Exception:
                soup = BeautifulSoup(html, "html.parser")
            artifact = artifact_from_soup(competitor, url, html, soup, "playwright_deep")
            artifact.modal_texts = modal_texts + tab_texts
            artifact.hidden_text = collect_hidden_text(soup)
            if clicked or tab_texts:
                artifact.raw_text = merge_text_blocks([artifact.raw_text, "=== ТЕКСТ ИЗ ВКЛАДОК ===\n" + "\n\n".join(tab_texts)])
                artifact.cleaned_text = clean_text(artifact.raw_text)
                artifact.status = f"success_expanded_{clicked}_controls_{len(tab_texts)}_tabs"
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
    candidates = page.locator("button, a, [role='button'], summary, [aria-expanded='false'], [data-qa-type*='accordion']")
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


def click_tabs_and_collect_text(page, progress: ProgressCallback, competitor: str) -> List[str]:
    collected: List[str] = []
    selectors = [
        "[role='tab']",
        "button[data-qa-type*='segmented-item']",
        "[data-qa-type*='segmented-item']",
        "button[aria-selected]",
        "[role='tablist'] button",
    ]
    seen_labels = set()
    clicked = 0
    for selector in selectors:
        try:
            candidates = page.locator(selector)
            count = min(candidates.count(), 80)
        except Exception:
            continue
        for index in range(count):
            try:
                element = candidates.nth(index)
                label = get_interactive_label(element)
                if not label or label in seen_labels:
                    continue
                if not TAB_TEXT_RE.search(label):
                    continue
                seen_labels.add(label)
                before_url = page.url
                element.scroll_into_view_if_needed(timeout=1200)
                element.click(timeout=1200)
                page.wait_for_timeout(700)
                try:
                    page.wait_for_load_state("networkidle", timeout=2500)
                except Exception:
                    pass
                if page.url != before_url:
                    page.go_back(wait_until="domcontentloaded", timeout=5000)
                    continue
                text = collect_current_main_text(page)
                if text:
                    collected.append(f"Вкладка: {label}\n{text}")
                clicked += 1
            except Exception:
                continue
    progress("tabs", competitor, f"Открыто вкладок/переключателей: {clicked}.")
    return collected


def get_interactive_label(element) -> str:
    parts: List[str] = []
    for getter in [
        lambda: element.inner_text(timeout=500),
        lambda: element.get_attribute("aria-label"),
        lambda: element.get_attribute("title"),
        lambda: element.get_attribute("data-qa-type"),
    ]:
        try:
            value = getter()
            if value:
                parts.append(str(value))
        except Exception:
            pass
    return clean_text(" ".join(parts))[:160]


def collect_current_main_text(page) -> str:
    selectors = ["main", "[role='main']", "article", "body"]
    for selector in selectors:
        try:
            text = clean_text(page.locator(selector).first.inner_text(timeout=1200))
            if len(text) > 120:
                return text
        except Exception:
            continue
    return ""


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
    embedded_json_text = extract_embedded_json_text(soup)
    faq_items = extract_faq(soup)
    tables = extract_tables(soup)
    pdf_links = extract_document_links(soup, url)
    iframe_urls = [urljoin(url, item.get("src", "")) for item in soup.find_all("iframe") if item.get("src")]
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    text_parts = [
        extract_main_content_text(soup),
        format_faq(faq_items),
        format_tables(tables),
        collect_hidden_text(soup),
        embedded_json_text,
    ]
    raw_text = merge_text_blocks(text_parts)
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


def extract_main_content_text(soup: BeautifulSoup) -> str:
    blocks: List[str] = []
    selectors = [
        "main",
        "[role='main']",
        "article",
        "[data-qa*='content']",
        "[data-test*='content']",
        "[class*='content']",
        "[class*='main']",
    ]
    for selector in selectors:
        for node in soup.select(selector)[:20]:
            text = clean_text(node.get_text("\n", strip=True))
            if len(text) > 120:
                blocks.append(text)

    soup_copy = BeautifulSoup(str(soup), "html.parser")
    for node in soup_copy.select("header, nav, footer, aside, [role='navigation'], [aria-label*='навигац'], [aria-label*='navigation']"):
        node.decompose()
    body_text = clean_text(soup_copy.get_text("\n", strip=True))
    if body_text:
        blocks.append(body_text)
    return merge_text_blocks(blocks)


def extract_embedded_json_text(soup: BeautifulSoup) -> str:
    chunks: List[str] = []
    for script in soup.find_all("script")[:80]:
        script_type = (script.get("type") or "").lower()
        script_id = (script.get("id") or "").lower()
        text = script.string or script.get_text(" ", strip=True)
        if not text or len(text) < 80:
            continue
        if "json" not in script_type and "__next_data__" not in script_id and "window.__" not in text[:200].lower():
            continue
        readable = json_to_readable_text(text)
        if readable:
            chunks.append(readable)
    return merge_text_blocks(chunks[:20])


def json_to_readable_text(text: str) -> str:
    try:
        data = json.loads(text)
    except Exception:
        return clean_text(" ".join(re.findall(r'"([^"{}]{4,180})"', text)[:1500]))
    values: List[str] = []
    collect_json_strings(data, values)
    return clean_text("\n".join(values[:1500]))


def collect_json_strings(value: object, values: List[str]) -> None:
    if isinstance(value, str):
        cleaned = clean_text(value)
        if len(cleaned) >= 4 and re.search(r"[А-Яа-яA-Za-z]", cleaned):
            values.append(cleaned)
    elif isinstance(value, list):
        for item in value[:200]:
            collect_json_strings(item, values)
    elif isinstance(value, dict):
        for item in list(value.values())[:200]:
            collect_json_strings(item, values)


def merge_text_blocks(blocks: List[str]) -> str:
    seen = set()
    result: List[str] = []
    for block in blocks:
        for paragraph in re.split(r"\n{2,}", clean_text(block)):
            normalized = re.sub(r"\W+", "", paragraph.lower())[:220]
            if len(paragraph) < 3 or normalized in seen:
                continue
            seen.add(normalized)
            result.append(paragraph)
    return "\n\n".join(result)


def unique_list(values: List[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


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
    text = repair_mojibake(text or "")
    text = re.sub(r"\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def looks_like_mojibake(text: str) -> bool:
    if not text:
        return False
    sample = text[:20000]
    bad_tokens = ["Ð", "Ñ", "Â", "â€", "â€™", "â€œ", "â€", "â€“", "â€”", "�"]
    bad_count = sum(sample.count(token) for token in bad_tokens)
    cyrillic_count = len(re.findall(r"[А-Яа-яЁё]", sample))
    return bad_count >= 3 and bad_count > cyrillic_count * 0.08


def repair_mojibake(text: str) -> str:
    if not text:
        return ""
    repaired = text
    for _ in range(2):
        if not looks_like_mojibake(repaired):
            break
        candidates = [repaired]
        for source_encoding in ("latin1", "cp1252"):
            try:
                candidates.append(repaired.encode(source_encoding, errors="ignore").decode("utf-8", errors="ignore"))
            except Exception:
                pass
        repaired = min(candidates, key=mojibake_score)
    return normalize_unicode_punctuation(repaired)


def mojibake_score(text: str) -> int:
    bad_tokens = ["Ð", "Ñ", "Â", "â€", "â€™", "â€œ", "â€", "â€“", "â€”", "�"]
    return sum(text.count(token) for token in bad_tokens)


def normalize_unicode_punctuation(text: str) -> str:
    replacements = {
        "\u00a0": " ",
        "Â ": " ",
        "Â": "",
        "â€”": "—",
        "â€“": "–",
        "â€‘": "‑",
        "â€œ": "«",
        "â€": "»",
        "â€™": "’",
        "â€¦": "…",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


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


def prioritize_chunks(chunks: List[str], parameters: List[str], research_type: str = "") -> List[str]:
    if not chunks:
        return []
    keywords = relevance_keywords(parameters, research_type)
    scored = [(chunk_relevance_score(chunk, keywords), index, chunk) for index, chunk in enumerate(chunks)]
    scored.sort(key=lambda item: (-item[0], item[1]))
    high = [chunk for score, _, chunk in scored if score > 0]
    low = [chunk for score, _, chunk in scored if score <= 0]
    return high + low


def relevance_keywords(parameters: List[str], research_type: str = "") -> List[str]:
    base = [
        "ставка",
        "процент",
        "пск",
        "полная стоимость",
        "сумма",
        "срок",
        "лет",
        "месяц",
        "залог",
        "авто",
        "автомоб",
        "заемщик",
        "заёмщик",
        "требован",
        "документ",
        "комисс",
        "страхован",
        "погашен",
        "налич",
        "кредит",
        "тариф",
        "услов",
    ]
    text = " ".join(parameters + [research_type])
    words = re.findall(r"[A-Za-zА-Яа-я0-9]{4,}", text.lower())
    return unique_list(base + words)


def chunk_relevance_score(chunk: str, keywords: List[str]) -> int:
    lowered = chunk.lower()
    score = 0
    for keyword in keywords:
        if keyword and keyword in lowered:
            score += 1
    if re.search(r"\d[\d\s]*(?:₽|руб|%)", lowered):
        score += 4
    if re.search(r"\b(?:пск|ставк|срок|сумм|требован|документ|комисс)", lowered):
        score += 5
    return score


def artifact_to_cache_value(artifact: SourceArtifact) -> Dict[str, object]:
    return asdict(artifact)


def decode_response_text(response: requests.Response) -> str:
    content_type = response.headers.get("content-type", "")
    charset_match = re.search(r"charset=([\w.-]+)", content_type, re.I)
    encodings = []
    if charset_match:
        encodings.append(charset_match.group(1))
    if response.encoding:
        encodings.append(response.encoding)
    if response.apparent_encoding:
        encodings.append(response.apparent_encoding)
    encodings.extend(["utf-8", "cp1251"])
    for encoding in unique_list(encodings):
        try:
            decoded = response.content.decode(encoding, errors="replace")
            if not looks_like_mojibake(decoded):
                return decoded
        except Exception:
            continue
    return repair_mojibake(response.text)
