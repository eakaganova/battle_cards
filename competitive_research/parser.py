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
    r"показать|ещ[её]|подробнее|раскрыть|читать|more|show|expand|details|faq|условия|кто|как|какие|какой|можно|нужно|почему|что|где|когда|сколько",
    re.I,
)

ACCORDION_SELECTOR = (
    "button, a, [role='button'], summary, [aria-expanded='false'], "
    "[data-qa-type*='accordion'], "
    "[class*='accordion-title'], "
    "[class*='accordion'][role='button'], "
    "[class*='Accordion'][role='button']"
)

TAB_TEXT_RE = re.compile(
    r"тариф|услов|документ|погашен|вопрос|ответ|требован|ставк|пск|комисс|страх|оформ|получ|залог|выгод|максимум|faq|documents|tariff|terms",
    re.I,
)

TAB_SELECTOR = (
    '[role="tab"], '
    'button[data-qa-type*="segmented-item"], '
    '[data-qa-type*="segmented-item"], '
    'button[aria-selected], '
    '[role="tablist"] button, '
    'li[class*="TabTitle"], '
    'li[class*="tabs-header"], '
    'ul[class*="TabTitleContainer"] > li, '
    '[class*="TabTitleHorizontal"], '
    '[class*="TabTitleSelector"]'
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
            progress("playwright", competitor, "Открываю страницу в браузере и коротко проверяю динамические блоки.")
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
            started_at = time.monotonic()
            page.goto(url, wait_until="domcontentloaded", timeout=config.playwright_timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=config.playwright_networkidle_timeout_ms)
            except PlaywrightTimeoutError:
                progress("dynamic", competitor, "Страница продолжает фоновые загрузки, использую уже отрисованный контент.")
            click_cookie_banners(page)
            scroll_deep(page, progress, competitor)
            if budget_exhausted(started_at, config.browser_interaction_budget_seconds):
                progress("dynamic", competitor, "Бюджет браузерной проверки исчерпан, перехожу к извлечению текущего DOM.")
                clicked = 0
                accordion_texts = []
                tab_texts = []
            else:
                clicked, accordion_texts = click_expandable(page, progress, competitor, config.accordion_budget_seconds)
                remaining_budget = max(2.0, config.browser_interaction_budget_seconds - (time.monotonic() - started_at))
                tab_texts = click_tabs_and_collect_text(page, progress, competitor, min(config.tabs_budget_seconds, remaining_budget))
            modal_texts = collect_modal_texts(page, progress, competitor)
            html = page.content()
            try:
                soup = BeautifulSoup(html, "lxml")
            except Exception:
                soup = BeautifulSoup(html, "html.parser")
            artifact = artifact_from_soup(competitor, url, html, soup, "playwright_deep")
            artifact.modal_texts = modal_texts + tab_texts + accordion_texts
            artifact.hidden_text = collect_hidden_text(soup)
            if clicked or tab_texts or accordion_texts:
                artifact.raw_text = merge_text_blocks(
                    [
                        artifact.raw_text,
                        "=== ТЕКСТ ИЗ РАСКРЫТЫХ FAQ/ACCORDION ===\n" + "\n\n".join(accordion_texts),
                        "=== ТЕКСТ ИЗ ВКЛАДОК ===\n" + "\n\n".join(tab_texts),
                    ]
                )
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
    rounds = 0
    for _ in range(5):
        height = page.evaluate("document.body.scrollHeight")
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(350)
        rounds += 1
        if height == previous_height:
            break
        previous_height = height
    progress("dynamic", competitor, f"Прокрутка завершена, раундов: {rounds}.")


def click_expandable(page, progress: ProgressCallback, competitor: str, budget_seconds: float = 6.0) -> tuple[int, List[str]]:
    started_at = time.monotonic()
    collected: List[str] = []
    dom_collected, dom_clicked, dom_labels = click_accordions_with_dom_api(page, budget_seconds)
    collected.extend(dom_collected)
    clicked = 0
    candidates = page.locator(ACCORDION_SELECTOR)
    count = min(candidates.count(), 60)
    for index in range(count):
        if budget_exhausted(started_at, budget_seconds):
            break
        try:
            element = candidates.nth(index)
            label = " ".join((element.inner_text(timeout=180) or element.get_attribute("aria-label") or "").split())
            if not label or not EXPAND_TEXT_RE.search(label):
                continue
            before_url = page.url
            element.click(timeout=350)
            page.wait_for_timeout(220)
            if page.url != before_url:
                page.go_back(wait_until="domcontentloaded", timeout=2500)
            clicked += 1
            text = collect_current_main_text(page)
            if text:
                collected.append(f"Раскрытый блок: {label}\n{text}")
        except Exception:
            continue
    total_clicked = clicked + dom_clicked
    labels_preview = ", ".join(unique_list(dom_labels)[:8])
    suffix = f" Найдено кандидатов: {len(unique_list(dom_labels))}. Кандидаты: {labels_preview}" if labels_preview else ""
    progress("accordion", competitor, f"Раскрыто FAQ/accordion/show-more элементов: {total_clicked}.{suffix}")
    return total_clicked, collected


def click_accordions_with_dom_api(page, budget_seconds: float = 6.0) -> tuple[List[str], int, List[str]]:
    started_at = time.monotonic()
    collected: List[str] = []
    labels: List[str] = []
    clicked = 0
    for frame in page.frames:
        try:
            candidates = frame.evaluate(
                """
                (selector) => Array.from(document.querySelectorAll(selector)).map((el, index) => ({
                    index,
                    text: (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim(),
                    expanded: el.getAttribute('aria-expanded') || '',
                    role: el.getAttribute('role') || '',
                    className: el.className || ''
                }))
                """,
                ACCORDION_SELECTOR,
            )
        except Exception:
            continue
        for candidate in candidates[:80]:
            if budget_exhausted(started_at, budget_seconds):
                return collected, clicked, labels
            label = clean_text(str(candidate.get("text", "")))
            if not label:
                continue
            labels.append(label)
            if not is_expandable_label(label, str(candidate.get("className", ""))):
                continue
            try:
                frame.evaluate(
                    """
                    (payload) => {
                        const items = Array.from(document.querySelectorAll(payload.selector));
                        const el = items[payload.index];
                        if (!el) return false;
                        el.scrollIntoView({block: 'center', inline: 'center'});
                        el.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, cancelable: true}));
                        el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
                        el.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, cancelable: true}));
                        el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true}));
                        el.click();
                        return true;
                    }
                    """,
                    {"index": candidate["index"], "selector": ACCORDION_SELECTOR},
                )
                page.wait_for_timeout(280)
                text = collect_frame_main_text(frame)
                if text:
                    collected.append(f"Раскрытый блок: {label}\n{text}")
                clicked += 1
            except Exception:
                continue
    return collected, clicked, labels


def is_expandable_label(label: str, class_name: str = "") -> bool:
    if EXPAND_TEXT_RE.search(label):
        return True
    if "accordion" in class_name.lower():
        return True
    return "?" in label and len(label) <= 220


def click_tabs_and_collect_text(page, progress: ProgressCallback, competitor: str, budget_seconds: float = 7.0) -> List[str]:
    started_at = time.monotonic()
    collected: List[str] = []
    js_collected, js_clicked, js_labels = click_tabs_with_dom_api(page, budget_seconds)
    collected.extend(js_collected)

    selectors = [
        "[role='tab']",
        "button[data-qa-type*='segmented-item']",
        "[data-qa-type*='segmented-item']",
        "button[aria-selected]",
        "[role='tablist'] button",
        "li[class*='TabTitle']",
        "li[class*='tabs-header']",
        "ul[class*='TabTitleContainer'] > li",
        "[class*='TabTitleHorizontal']",
    ]
    seen_labels = set()
    clicked = js_clicked
    if budget_exhausted(started_at, budget_seconds):
                labels_preview = ", ".join(unique_list(js_labels)[:8])
                suffix = f" Найдено вкладок: {len(unique_list(js_labels))}. Кандидаты: {labels_preview}" if labels_preview else ""
                progress("tabs", competitor, f"Открыто вкладок/переключателей: {clicked}.{suffix}")
                return collected
    for selector in selectors:
        try:
            candidates = page.locator(selector)
            count = min(candidates.count(), 35)
        except Exception:
            continue
        for index in range(count):
            if budget_exhausted(started_at, budget_seconds):
                break
            try:
                element = candidates.nth(index)
                label = get_interactive_label(element)
                if not label or label in seen_labels:
                    continue
                if not TAB_TEXT_RE.search(label):
                    continue
                seen_labels.add(label)
                before_url = page.url
                element.scroll_into_view_if_needed(timeout=450)
                element.click(timeout=450)
                page.wait_for_timeout(350)
                if page.url != before_url:
                    page.go_back(wait_until="domcontentloaded", timeout=2500)
                    continue
                text = collect_current_main_text(page)
                if text:
                    collected.append(f"Вкладка: {label}\n{text}")
                clicked += 1
            except Exception:
                continue
    labels_preview = ", ".join(unique_list(js_labels)[:8])
    suffix = f" Найдено вкладок: {len(unique_list(js_labels))}. Кандидаты: {labels_preview}" if labels_preview else ""
    progress("tabs", competitor, f"Открыто вкладок/переключателей: {clicked}.{suffix}")
    return collected


def click_tabs_with_dom_api(page, budget_seconds: float = 7.0) -> tuple[List[str], int, List[str]]:
    started_at = time.monotonic()
    collected: List[str] = []
    labels: List[str] = []
    clicked = 0
    for frame in page.frames:
        try:
            candidates = frame.evaluate(
                """
                (selector) => Array.from(document.querySelectorAll(selector)).map((el, index) => ({
                    index,
                    text: (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim(),
                    qa: el.getAttribute('data-qa-type') || '',
                    selected: el.getAttribute('aria-selected') || '',
                    active: el.getAttribute('data-active') || ''
                }))
                """,
                TAB_SELECTOR,
            )
        except Exception:
            continue
        for candidate in candidates[:100]:
            if budget_exhausted(started_at, budget_seconds):
                return collected, clicked, labels
            label = clean_text(" ".join([candidate.get("text", ""), candidate.get("qa", "")]))
            if not label:
                continue
            labels.append(label)
            if not TAB_TEXT_RE.search(label):
                continue
            try:
                before_url = page.url
                frame.evaluate(
                    """
                    (payload) => {
                        const items = Array.from(document.querySelectorAll(payload.selector));
                        const el = items[payload.index];
                        if (!el) return false;
                        el.scrollIntoView({block: 'center', inline: 'center'});
                        el.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, cancelable: true}));
                        el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
                        el.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, cancelable: true}));
                        el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true}));
                        el.click();
                        return true;
                    }
                    """,
                    {"index": candidate["index"], "selector": TAB_SELECTOR},
                )
                page.wait_for_timeout(350)
                if page.url != before_url:
                    page.go_back(wait_until="domcontentloaded", timeout=2500)
                    continue
                text = collect_frame_main_text(frame)
                if text:
                    collected.append(f"Вкладка: {label}\n{text}")
                clicked += 1
            except Exception:
                continue
    return collected, clicked, labels


def budget_exhausted(started_at: float, budget_seconds: float) -> bool:
    return time.monotonic() - started_at >= budget_seconds


def collect_frame_main_text(frame) -> str:
    try:
        text = frame.evaluate(
            """
            () => {
                const main = document.querySelector('main,[role="main"],article') || document.body;
                return main ? main.innerText : '';
            }
            """
        )
        return clean_text(text)
    except Exception:
        return ""


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


def prepare_text_for_llm(text: str) -> str:
    cleaned = clean_text(text)
    cleaned = remove_repeated_ui_lines(cleaned)
    cleaned = deduplicate_exact_paragraphs(cleaned)
    return clean_text(cleaned)


def remove_repeated_ui_lines(text: str) -> str:
    lines: List[str] = []
    seen_counts: Dict[str, int] = {}
    for line in text.splitlines():
        line = clean_text(line)
        if not line:
            lines.append("")
            continue
        normalized = normalize_for_dedupe(line)
        if len(normalized) < 8:
            continue
        seen_counts[normalized] = seen_counts.get(normalized, 0) + 1
        if is_low_value_ui_line(line) and seen_counts[normalized] > 1:
            continue
        lines.append(line)
    return "\n".join(lines)


def deduplicate_exact_paragraphs(text: str) -> str:
    paragraphs = re.split(r"\n{2,}", text)
    result: List[str] = []
    seen = set()
    for paragraph in paragraphs:
        paragraph = clean_text(paragraph)
        if not paragraph:
            continue
        normalized = normalize_for_dedupe(paragraph)
        if len(normalized) < 20:
            result.append(paragraph)
            continue
        fingerprint = normalized
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(paragraph)
    return "\n\n".join(result)


def is_low_value_ui_line(line: str) -> bool:
    if len(line) > 80:
        return False
    if re.search(r"\d|%|₽|руб|год|лет|месяц|ставк|пск|срок|сумм|кредит|залог", line.lower()):
        return False
    return bool(
        re.fullmatch(
            r"(меню|назад|далее|подробнее|открыть|закрыть|показать|скрыть|выбрать|оформить|оставить заявку|перезвоните мне|войти|личный кабинет|cookie|ok|accept)",
            line.strip().lower(),
        )
    )



def normalize_for_dedupe(text: str) -> str:
    lowered = text.lower().replace("ё", "е")
    lowered = re.sub(r"[^0-9a-zа-я]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


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
    if not text.strip():
        return []
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


def select_focused_chunks(
    chunks: List[str],
    parameters: List[str],
    research_type: str = "",
    max_chunks: int = 3,
) -> List[str]:
    if not chunks:
        return []
    max_chunks = max(1, max_chunks)
    keywords = relevance_keywords(parameters, research_type)
    scored = [(chunk_relevance_score(chunk, keywords), index, chunk) for index, chunk in enumerate(chunks)]
    scored.sort(key=lambda item: (-item[0], item[1]))
    relevant = [item for item in scored if item[0] > 0]
    selected = relevant[:max_chunks] if relevant else scored[:max_chunks]
    first_chunk = next((item for item in scored if item[1] == 0), None)
    if first_chunk and all(item[1] != 0 for item in selected):
        selected = [first_chunk] + selected[: max_chunks - 1]
    selected.sort(key=lambda item: item[1])
    return [chunk for _, _, chunk in selected]


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
        "накопительн",
        "счет",
        "счёт",
        "доход",
        "доходност",
        "пополн",
        "снят",
        "процент",
        "вклад",
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
