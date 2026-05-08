import streamlit as st
from openai import OpenAI
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import hashlib
import time


# =========================
# CONFIG
# =========================

client = OpenAI()

MAX_DEPTH = 2
WAIT_AFTER_CLICK = 0.8


PRODUCT_BANK_URLS = {
    "КНЗ: кредит под залог недвижимости": [
        {"name": "Сбер", "url": "https://www.sberbank.ru/ru/person/credits/money/credit_zalog"},
        {"name": "ВТБ", "url": "https://www.vtb.ru/personal/ipoteka/ipoteka-pod-zalog-nedvizhimosti/"},
        {"name": "Совкомбанк", "url": "https://sovcombank.ru/credits/cash/alternativa"},
        {"name": "МТС Банк", "url": "https://www.mtsbank.ru/chastnim-licam/ipoteka/kredit-pod-zalog/"},
        {"name": "Газпромбанк", "url": "https://www.gazprombank.ru/personal/bail/pod-zalog/"},
        {"name": "Альфа-Банк", "url": "https://alfabank.ru/get-money/credit/pod-zalog/"},
    ],
    "КНА: кредит под залог автомобиля": [
        {"name": "Т-Банк", "url": "https://www.tbank.ru/loans/cash-loan/auto/"},
        {"name": "Совкомбанк", "url": "https://sovcombank.ru/credits/cash/pod-zalog-avto-"},
        {"name": "ВТБ", "url": "https://www.vtb.ru/personal/kredit/pod-zalog-avto/"},
    ],
}


# =========================
# LLM
# =========================

def call_llm(prompt: str):
    response = client.responses.create(
        model="gpt-5.3-mini",
        input=prompt
    )

    try:
        return response.output[0].content[0].text
    except Exception:
        return None


# =========================
# HTML PROCESSING
# =========================

def hash_text(text):
    return hashlib.md5(text.encode()).hexdigest()


def clean_html(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    return soup.get_text("\n")


# =========================
# BROWSER LOGIC
# =========================

def expand_accordions(page):
    selectors = [
        "[data-testid*='accordion']",
        ".accordion",
        "button[aria-expanded]",
        "details summary"
    ]

    for sel in selectors:
        items = page.locator(sel).all()
        for item in items:
            try:
                item.click()
            except:
                pass


def extract_all_tabs(page):
    pages = []

    tab_selectors = [
        "[role='tab']",
        ".tabs__item",
        "button[aria-controls]",
        ".tab"
    ]

    tabs = []
    for sel in tab_selectors:
        tabs.extend(page.locator(sel).all())

    if not tabs:
        return [page.content()]

    for i in range(len(tabs)):
        try:
            tabs[i].click()
            page.wait_for_timeout(int(WAIT_AFTER_CLICK * 1000))
            pages.append(page.content())
        except:
            continue

    return pages


def extract_internal_links(page, base_url):
    try:
        links = page.locator("a").evaluate_all("els => els.map(e => e.href)")
    except:
        return []

    return list(set([l for l in links if l and base_url in l]))


# =========================
# CRAWLER
# =========================

def crawl(url):
    visited = set()
    queue = [(url, 0)]
    pages = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        while queue:
            current_url, depth = queue.pop(0)

            if current_url in visited or depth > MAX_DEPTH:
                continue

            visited.add(current_url)

            page = browser.new_page()

            try:
                page.goto(current_url, wait_until="networkidle", timeout=60000)

                expand_accordions(page)

                tab_pages = extract_all_tabs(page)
                pages.extend(tab_pages)

                links = extract_internal_links(page, url)
                for l in links:
                    queue.append((l, depth + 1))

            except:
                pass
            finally:
                page.close()

        browser.close()

    return pages


# =========================
# NORMALIZATION
# =========================

def normalize(html_pages):
    seen = set()
    texts = []

    for html in html_pages:
        h = hash_text(html)
        if h in seen:
            continue

        seen.add(h)
        texts.append(clean_html(html))

    return "\n\n".join(texts)


# =========================
# PROMPTS
# =========================

def build_prompt(battle_card_type, bank_name, url, text, structure):
    return (
        f"Тип баттл-карты: {battle_card_type}\n"
        f"Банк: {bank_name}\n"
        f"Источник: {url}\n\n"
        "Работай строго по тексту.\n"
        "Не используй внешние знания.\n"
        "Если нет данных — пиши: Не указано.\n"
        "Если есть расхождения — фиксируй оба значения.\n\n"
        f"{structure}\n\n"
        f"ТЕКСТ:\n\n{text}"
    )


# =========================
# PIPELINE
# =========================

def run_pipeline(battle_card_type):
    results = []

    for bank in PRODUCT_BANK_URLS[battle_card_type]:
        name = bank["name"]
        url = bank["url"]

        html_pages = crawl(url)
        text = normalize(html_pages)

        prompt = build_prompt(
            battle_card_type,
            name,
            url,
            text,
            structure="""
## Основные параметры кредита
| Параметр | Содержание |
|---|---|
| Название банка | |
| Процентная ставка | |
| ПСК | |
| Сумма | |
| Срок | |
"""
        )

        llm_result = call_llm(prompt)

        results.append({
            "bank": name,
            "url": url,
            "result": llm_result
        })

    return results


# =========================
# STREAMLIT UI
# =========================

st.set_page_config(page_title="Bank Battle Cards", layout="wide")

st.title("Bank Battle Card Extractor")

battle_card_type = st.selectbox(
    "Тип продукта",
    list(PRODUCT_BANK_URLS.keys())
)

if st.button("Запустить парсинг"):
    with st.spinner("Собираю данные..."):
        data = run_pipeline(battle_card_type)

    st.success("Готово")

    for item in data:
        st.subheader(item["bank"])
        st.write(item["url"])

        if item["result"]:
            st.markdown(item["result"])
        else:
            st.error("LLM вернул пустой ответ")
