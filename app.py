import os
import time
import traceback

import openai
import requests
import streamlit as st

from bs4 import BeautifulSoup

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

YANDEX_MODEL = "gpt-oss-120b/latest"

# =========================
# STREAMLIT CONFIG
# =========================

st.set_page_config(
    page_title="Battle Cards",
    layout="wide"
)

# =========================
# ENV CHECK
# =========================

if not YANDEX_FOLDER or not YANDEX_API_KEY:
    st.error(
        "Не заданы переменные окружения "
        "YANDEX_FOLDER и/или YANDEX_API_KEY"
    )
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
        st.session_state.logs[-500:]
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
# HTML FETCH
# =========================

def fetch_html(url):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=40
    )

    response.raise_for_status()

    return response.text

# =========================
# HTML -> TEXT
# =========================

def extract_text_from_html(html):

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup([
        "script",
        "style",
        "noscript",
        "svg",
        "iframe"
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

# =========================
# PAGE PARSER
# =========================

def get_page_text(url):

    html = fetch_html(url)

    log(f"HTML size: {len(html)}")

    text = extract_text_from_html(html)

    log(f"Extracted text size: {len(text)}")

    preview = text[:1000] if text else "EMPTY"

    log(f"Extracted preview:\n{preview}")

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
| Максимальная сумма кредита | |
| Минимальная сумма кредита | |
| Срок | |
| LTV | |
| Страхование | |
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
| Срок | |
| Максимальная сумма | |

## Залог

| Параметр | Содержание |
|---|---|
| Требуется ли авто в залог | |
| LTV | |
| Ограничения | |
"""

    return """
## Параметры

| Параметр | Содержание |
|---|---|
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
ТИП ПРОДУКТА:
{battle_card_type}

БАНК:
{bank_name}

URL:
{url}

ПРАВИЛА:
- Используй только текст источника.
- Не додумывай информацию.
- Если информации нет, пиши "Не указано".
- Если информация указана косвенно, пиши "Упоминается косвенно".
- Не используй знания вне источника.
- Верни результат строго по шаблону.

СТРУКТУРА:
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

                log(f"START: {bank_name}")
                log(f"URL: {bank_url}")

                page_text = get_page_text(
                    bank_url
                )

                if (
                    not page_text
                    or len(page_text.strip()) < 1000
                ):

                    size = (
                        len(page_text)
                        if page_text
                        else 0
                    )

                    log(
                        f"TEXT TOO SMALL: "
                        f"{bank_name} ({size})"
                    )

                    all_results.append(
                        f"""
## {bank_name}

Не удалось извлечь достаточный объём текста.

Размер текста: {size}

URL: {bank_url}
"""
                    )

                    continue

                log(
                    f"Final input size: "
                    f"{len(page_text)}"
                )

                limited_text = page_text[:50000]

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
                    f"LLM анализ: {bank_name}"
                )

                response = client.responses.create(
                    model=(
                        f"gpt://"
                        f"{YANDEX_FOLDER}/"
                        f"{YANDEX_MODEL}"
                    ),
                    temperature=0.2,
                    input=prompt,
                    max_output_tokens=2500
                )

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

                    continue

                all_results.append(
                    result_text
                )

            except Exception:

                log(
                    f"ERROR BANK: "
                    f"{bank['name']}"
                )

                log(
                    traceback.format_exc()
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

# =========================
# UI
# =========================

st.title("Battle Cards Generator")

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
