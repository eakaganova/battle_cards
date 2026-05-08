import os
import time
import traceback

import openai
import requests
import streamlit as st

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


# =========================
# CONFIG
# =========================

PRODUCT_BANK_URLS = {
    "КНЗ: кредит под залог недвижимости": [
        {
            "name": "Сбер",
            "url": "https://www.sberbank.ru/ru/person/credits/money/credit_zalog"
        },
        {
            "name": "ВТБ",
            "url": "https://www.vtb.ru/personal/ipoteka/ipoteka-pod-zalog-nedvizhimosti/"
        },
        {
            "name": "Совкомбанк",
            "url": "https://sovcombank.ru/credits/cash/alternativa"
        },
        {
            "name": "МТС Банк",
            "url": "https://www.mtsbank.ru/chastnim-licam/ipoteka/kredit-pod-zalog/"
        },
        {
            "name": "Газпромбанк",
            "url": "https://www.gazprombank.ru/personal/bail/pod-zalog/"
        },
        {
            "name": "Альфа-Банк",
            "url": "https://alfabank.ru/get-money/credit/pod-zalog/"
        },
    ],

    "КНА: кредит под залог автомобиля": [
        {
            "name": "Т-Банк",
            "url": "https://www.tbank.ru/loans/cash-loan/auto/"
        },
        {
            "name": "Совкомбанк",
            "url": "https://sovcombank.ru/credits/cash/pod-zalog-avto-"
        },
        {
            "name": "ВТБ",
            "url": "https://www.vtb.ru/personal/kredit/pod-zalog-avto/"
        },
    ],

    "Кредит наличными": [
        {
            "name": "Сбер",
            "url": "https://www.sberbank.ru"
        },
        {
            "name": "ВТБ",
            "url": "https://www.vtb.ru"
        },
    ]
}


# =========================
# ENV
# =========================

YANDEX_FOLDER = os.getenv("YANDEX_FOLDER")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_MODEL = os.getenv("YANDEX_MODEL", "gpt-oss-120b/latest")


# =========================
# STREAMLIT CONFIG
# =========================

st.set_page_config(
    page_title="Battle Cards",
    layout="wide"
)


# =========================
# SESSION STATE
# =========================

if "logs" not in st.session_state:
    st.session_state.logs = []

if "status" not in st.session_state:
    st.session_state.status = "Idle"


# =========================
# LOGGING
# =========================

def log(message):
    ts = time.strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{ts}] {message}")


def render_logs():
    st.subheader("Логи")

    logs_text = "\n".join(
        st.session_state.logs[-700:]
    )

    st.code(logs_text)


# =========================
# STATUS
# =========================

status_box = st.empty()


def set_status(message):
    st.session_state.status = message
    status_box.info(f"Статус: {message}")


# =========================
# ENV CHECK
# =========================

if not YANDEX_FOLDER or not YANDEX_API_KEY:
    st.error(
        "Не заданы переменные окружения YANDEX_FOLDER и/или YANDEX_API_KEY. "
        "На Render добавь их в Environment Variables."
    )
    render_logs()
    st.stop()


# =========================
# LLM CLIENT
# =========================

client = openai.OpenAI(
    api_key=YANDEX_API_KEY,
    base_url="https://ai.api.cloud.yandex.net/v1",
    project=YANDEX_FOLDER
)


# =========================
# TEXT QUALITY CHECK
# =========================

def is_bad_text(text):
    if not text:
        return True

    clean = text.strip()

    if len(clean) < 1500:
        return True

    bad_fragments = [
        "Ð",
        "Ñ",
        "Рџ",
        "Р°",
        "Рµ",
        "Рё",
        "РЅ",
        "Рѕ",
        "Рґ",
        "Р»",
        "Рє",
        "Р"
    ]

    bad_count = sum(
        clean.count(fragment)
        for fragment in bad_fragments
    )

    if bad_count > 20:
        return True

    return False


# =========================
# REQUESTS PARSER
# =========================

def fetch_html_requests(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=40
    )

    response.raise_for_status()

    if not response.encoding or response.encoding.lower() in [
        "iso-8859-1",
        "ascii"
    ]:
        response.encoding = response.apparent_encoding

    return response.text


def extract_text_from_html(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup([
        "script",
        "style",
        "noscript",
        "svg",
        "iframe",
        "canvas"
    ]):
        tag.decompose()

    text = soup.get_text(separator="\n")

    cleaned_lines = []

    for line in text.splitlines():
        line = line.strip()

        if line:
            cleaned_lines.append(line)

    final_text = "\n".join(cleaned_lines)

    return final_text


def get_text_with_requests(url):
    html = fetch_html_requests(url)

    log(f"Requests HTML size: {len(html)}")

    text = extract_text_from_html(html)

    log(f"Requests extracted text size: {len(text)}")
    log(f"Requests preview:\n{text[:1200] if text else 'EMPTY'}")

    return text


# =========================
# PLAYWRIGHT PARSER
# =========================

def safe_click_locator(locator, timeout=1000):
    try:
        if locator.is_visible():
            locator.click(timeout=timeout)
            return True
    except Exception:
        return False

    return False


def close_popups_and_cookies(page):
    close_texts = [
        "Принять",
        "Принять все",
        "Понятно",
        "Хорошо",
        "Согласен",
        "Согласиться",
        "Закрыть",
        "Не сейчас",
        "ОК",
        "OK"
    ]

    for text in close_texts:
        try:
            elements = page.get_by_text(text, exact=False)
            count = elements.count()

            for i in range(min(count, 7)):
                try:
                    element = elements.nth(i)

                    if safe_click_locator(element, timeout=1200):
                        page.wait_for_timeout(500)
                        log(f"Closed popup/cookie by text: {text}")

                except Exception:
                    pass

        except Exception:
            pass

    close_selectors = [
        "button[aria-label='Закрыть']",
        "button[aria-label='Close']",
        "[data-testid*='close']",
        "[class*='close']",
        "[class*='Close']"
    ]

    for selector in close_selectors:
        try:
            elements = page.locator(selector)
            count = elements.count()

            for i in range(min(count, 5)):
                try:
                    element = elements.nth(i)

                    if safe_click_locator(element, timeout=1000):
                        page.wait_for_timeout(400)
                        log(f"Closed popup by selector: {selector}")

                except Exception:
                    pass

        except Exception:
            pass


def click_by_visible_texts(page):
    click_texts = [
        "Показать ещё",
        "Показать еще",
        "Показать больше",
        "Подробнее",
        "Развернуть",
        "Раскрыть",
        "Все условия",
        "Условия",
        "Тарифы",
        "Документы",
        "Требования",
        "Как получить",
        "Как оформить",
        "Вопросы и ответы",
        "Часто задаваемые вопросы",
        "FAQ",
        "Ещё",
        "Еще",
        "Смотреть все",
        "Смотреть ещё",
        "Смотреть еще",
        "Читать далее",
        "Развернуть все"
    ]

    clicked_total = 0

    for text in click_texts:
        try:
            elements = page.get_by_text(text, exact=False)
            count = elements.count()

            for i in range(min(count, 12)):
                try:
                    element = elements.nth(i)

                    if safe_click_locator(element, timeout=1200):
                        clicked_total += 1
                        page.wait_for_timeout(500)
                        log(f"Clicked by text: {text}")

                except Exception:
                    pass

        except Exception:
            pass

    return clicked_total


def click_accordion_selectors(page):
    selectors = [
        "summary",
        "[role='button']",
        "[aria-expanded='false']",
        "button",
        "[class*='accordion']",
        "[class*='Accordion']",
        "[class*='spoiler']",
        "[class*='Spoiler']",
        "[class*='collapse']",
        "[class*='Collapse']",
        "[class*='faq']",
        "[class*='Faq']"
    ]

    clicked_total = 0

    for selector in selectors:
        try:
            elements = page.locator(selector)
            count = elements.count()

            for i in range(min(count, 45)):
                try:
                    element = elements.nth(i)

                    text = ""
                    try:
                        text = element.inner_text(timeout=500).strip()
                    except Exception:
                        pass

                    skip_words = [
                        "оформить",
                        "оставить заявку",
                        "получить кредит",
                        "войти",
                        "личный кабинет",
                        "скачать",
                        "позвонить"
                    ]

                    lowered = text.lower()

                    if any(word in lowered for word in skip_words):
                        continue

                    if safe_click_locator(element, timeout=900):
                        clicked_total += 1
                        page.wait_for_timeout(250)

                except Exception:
                    pass

        except Exception:
            pass

    if clicked_total:
        log(f"Clicked accordion-like elements: {clicked_total}")

    return clicked_total


def scroll_page(page, steps=6, pixels=2200):
    for _ in range(steps):
        page.mouse.wheel(0, pixels)
        page.wait_for_timeout(700)


def fetch_text_playwright(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-setuid-sandbox"
            ]
        )

        context = browser.new_context(
            locale="ru-RU",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={
                "width": 1440,
                "height": 1400
            },
            ignore_https_errors=True
        )

        page = context.new_page()

        page.set_default_timeout(10000)

        log("Playwright: opening page")

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(3000)

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            log("Playwright: networkidle timeout, continue anyway")

        close_popups_and_cookies(page)

        scroll_page(page, steps=5, pixels=2200)

        close_popups_and_cookies(page)

        click_by_visible_texts(page)
        click_accordion_selectors(page)

        for round_num in range(3):
            log(f"Playwright interaction round: {round_num + 1}")

            scroll_page(page, steps=3, pixels=2600)

            close_popups_and_cookies(page)

            clicked_texts = click_by_visible_texts(page)
            clicked_accordions = click_accordion_selectors(page)

            log(
                f"Round {round_num + 1}: "
                f"clicked_texts={clicked_texts}, "
                f"clicked_accordions={clicked_accordions}"
            )

        try:
            text = page.locator("body").inner_text(timeout=15000)
        except Exception:
            html = page.content()
            text = extract_text_from_html(html)

        context.close()
        browser.close()

        text = normalize_text(text)

        return text


# =========================
# TEXT NORMALIZATION
# =========================

def normalize_text(text):
    if not text:
        return ""

    lines = []

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        lines.append(line)

    # Убираем подряд идущие дубли строк.
    deduped = []
    prev = None

    for line in lines:
        if line != prev:
            deduped.append(line)

        prev = line

    return "\n".join(deduped)


def get_page_text(url):
    text = ""

    try:
        log("Trying requests parser")

        text = get_text_with_requests(url)

        text = normalize_text(text)

    except Exception:
        log("Requests parser error")
        log(traceback.format_exc())

    if is_bad_text(text):
        log("Requests text is weak. Trying Playwright browser parser.")

        try:
            text = fetch_text_playwright(url)

            log(f"Playwright extracted text size: {len(text)}")
            log(f"Playwright preview:\n{text[:1800] if text else 'EMPTY'}")

        except Exception:
            log("Playwright parser error")
            log(traceback.format_exc())

    else:
        log("Requests parser result accepted")

    return text


# =========================
# PROMPT STRUCTURE
# =========================

def get_structure(battle_card_type):
    if battle_card_type == "КНЗ: кредит под залог недвижимости":
        return """
## Основные параметры кредита

| Параметр | Содержание |
|---|---|
| Название банка | |
| URL источника | |
| Процентная ставка | |
| ПСК | |
| Максимальная сумма кредита | |
| Минимальная сумма кредита | |
| Срок | |
| LTV / доля от стоимости недвижимости | |
| Обеспечение / объект залога | |
| Страхование | |
| Требования к заёмщику | |
| Требования к недвижимости | |
| Подтверждение дохода | |
| Способ получения денег | |
| Досрочное погашение | |
| Комиссии | |
| Особые условия / ограничения | |
| Документы | |
| Как оформить | |
| Что не указано на странице | |
"""

    if battle_card_type == "КНА: кредит под залог автомобиля":
        return """
## Основные параметры кредита

| Параметр | Содержание |
|---|---|
| Название банка | |
| URL источника | |
| Процентная ставка | |
| ПСК | |
| Максимальная сумма | |
| Минимальная сумма | |
| Срок | |
| Требуется ли авто в залог | |
| LTV / доля от стоимости автомобиля | |
| Кто может пользоваться автомобилем | |
| Требования к автомобилю | |
| Требования к заёмщику | |
| Подтверждение дохода | |
| Страхование | |
| Комиссии | |
| Документы | |
| Как оформить | |
| Особые условия / ограничения | |
| Что не указано на странице | |
"""

    return """
## Параметры

| Параметр | Содержание |
|---|---|
| Название банка | |
| URL источника | |
| Процентная ставка | |
| ПСК | |
| Сумма | |
| Срок | |
| Требования к заёмщику | |
| Документы | |
| Страхование | |
| Комиссии | |
| Как оформить | |
| Что не указано на странице | |
"""


# =========================
# PROMPT
# =========================

def build_prompt(
    battle_card_type,
    bank_name,
    url,
    source_text
):
    structure = get_structure(
        battle_card_type
    )

    prompt = f"""
ТЫ — аналитик по банковским продуктам.

ЗАДАЧА:
Извлечь параметры продукта из текста страницы банка и оформить battle card.

ТИП ПРОДУКТА:
{battle_card_type}

БАНК:
{bank_name}

URL:
{url}

СТРОГИЕ ПРАВИЛА:
- Используй только текст источника ниже.
- Не додумывай информацию.
- Не используй внешние знания.
- Если информации нет, пиши: "Не указано".
- Если информация указана косвенно, пиши: "Упоминается косвенно: ..." и объясни, на основании какого фрагмента.
- Если на странице есть диапазон, сохрани диапазон.
- Если есть условия типа "от", "до", "при выполнении условий", обязательно сохрани эти оговорки.
- Не превращай "от 5%" в "5%".
- Не делай вывод о выгодности продукта.
- Верни результат строго по шаблону.

ШАБЛОН:
{structure}

ТЕКСТ ИСТОЧНИКА:
{source_text}
"""

    return prompt


# =========================
# SAFE RESPONSE PARSER
# =========================

def extract_llm_text(response):
    try:
        if (
            hasattr(response, "output_text")
            and response.output_text
        ):
            return response.output_text

        if (
            hasattr(response, "output")
            and response.output
        ):
            for item in response.output:
                if (
                    hasattr(item, "content")
                    and item.content
                ):
                    for content in item.content:
                        if (
                            hasattr(content, "text")
                            and content.text
                        ):
                            return content.text

    except Exception:
        return None

    return None


# =========================
# LLM CALL
# =========================

def call_llm(prompt):
    response = client.responses.create(
        model=(
            f"gpt://"
            f"{YANDEX_FOLDER}/"
            f"{YANDEX_MODEL}"
        ),
        temperature=0.2,
        input=prompt,
        max_output_tokens=3000
    )

    return response


# =========================
# PIPELINE
# =========================

def run_pipeline(
    battle_card_type,
    selected_banks
):
    try:
        st.session_state.logs = []

        set_status("Запуск")

        all_results = []

        for bank in selected_banks:
            try:
                bank_name = bank["name"]
                bank_url = bank["url"]

                set_status(
                    f"Парсинг: {bank_name}"
                )

                log("=" * 80)
                log(f"START: {bank_name}")
                log(f"URL: {bank_url}")

                page_text = get_page_text(
                    bank_url
                )

                page_text = normalize_text(
                    page_text
                )

                text_size = len(page_text) if page_text else 0

                log(
                    f"Final extracted text size: "
                    f"{text_size}"
                )

                if (
                    not page_text
                    or len(page_text.strip()) < 1000
                ):
                    log(
                        f"TEXT TOO SMALL AFTER ALL PARSERS: "
                        f"{bank_name} ({text_size})"
                    )

                    all_results.append(
                        f"""
## {bank_name}

Не удалось извлечь достаточный объём текста.

Размер текста: {text_size}

URL: {bank_url}
"""
                    )

                    continue

                limited_text = page_text[:70000]

                if len(page_text) > len(limited_text):
                    log(
                        f"Text truncated for prompt: "
                        f"{len(page_text)} -> {len(limited_text)}"
                    )

                prompt = build_prompt(
                    battle_card_type,
                    bank_name,
                    bank_url,
                    limited_text
                )

                log(
                    f"Prompt size: "
                    f"{len(prompt)}"
                )

                set_status(
                    f"LLM-анализ: {bank_name}"
                )

                response = call_llm(prompt)

                log(
                    "LLM response received"
                )

                result_text = extract_llm_text(
                    response
                )

                if not result_text:
                    log(
                        f"EMPTY OUTPUT: "
                        f"{bank_name}"
                    )

                    log(str(response))

                    all_results.append(
                        f"""
## {bank_name}

LLM вернула пустой ответ.

URL: {bank_url}
"""
                    )

                    continue

                all_results.append(
                    result_text
                )

            except Exception:
                log(
                    f"ERROR BANK: "
                    f"{bank.get('name', 'UNKNOWN')}"
                )

                log(
                    traceback.format_exc()
                )

                all_results.append(
                    f"""
## {bank.get("name", "UNKNOWN")}

Ошибка обработки банка.

```text
{traceback.format_exc()}

"""
)

    if not all_results:
        log("NO RESULTS")

        return None

    final_report = (
        "\n\n---\n\n"
        .join(all_results)
    )

    set_status("Готово")

    return final_report

except Exception:
    log("PIPELINE ERROR")
    log(traceback.format_exc())

    return None
=========================
UI
=========================

st.title("Battle Cards Generator")

st.caption(
"Парсер сначала пробует requests, затем при слабом результате запускает "
"Playwright: открывает страницу в headless-браузере, кликает раскрывающиеся "
"элементы и собирает текст."
)

battle_card_type = st.selectbox(
"Тип баттл-карты",
list(PRODUCT_BANK_URLS.keys())
)

banks = PRODUCT_BANK_URLS[
battle_card_type
]

selected_bank_names = st.multiselect(
"Банки",
[b["name"] for b in banks],
default=[b["name"] for b in banks]
)

selected_banks = [
b
for b in banks
if b["name"] in selected_bank_names
]

with st.expander("Текущие URL"):
for bank in selected_banks:
st.write(
f"{bank['name']} — {bank['url']}"
)

if st.button("Запустить анализ"):
result = run_pipeline(
battle_card_type,
selected_banks
)

if result:
    st.success("Готово")
    st.markdown(result)
else:
    st.error(
        "Получен пустой результат. "
        "Смотри логи."
    )

render_logs()
