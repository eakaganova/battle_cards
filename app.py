import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd

# =========================
# DATA
# =========================

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
    "Автокредит": [
        {"name": "ПСБ", "url": "https://www.psbank.ru/new-subjects/auto-start"},
        {"name": "Т-Банк", "url": "https://www.tbank.ru/loans/auto-loan/"},
        {"name": "Совкомбанк", "url": "https://sovcombank.ru/apply/auto/onlajn-zayavka-na-avtokredit/"},
        {"name": "Альфа-Банк", "url": "https://alfabank.ru/get-money/autocredit/"},
        {"name": "Сбер", "url": "https://www.sberbank.ru/ru/person/credits/money/avtokredit_ab"},
        {"name": "ВТБ", "url": "https://www.vtb.ru/personal/avtokredity/moskva/"},
    ],
    "Кредит наличными": [
        {"name": "Уралсиб", "url": "https://uralsib.ru/kredity/kredit-na-lyubye-tseli"},
        {"name": "ЛокоБанк", "url": "https://www.lockobank.ru/personal/kredit/nalichnymi/"},
        {"name": "Сбер", "url": "https://www.sberbank.ru/ru/person/credits/money/consumer_unsecured"},
        {"name": "Т-Банк", "url": "https://www.tbank.ru/loans/cash-loan/"},
        {"name": "Совкомбанк", "url": "https://sovcombank.ru/apply/credit/city-moskva/"},
        {"name": "Альфа-Банк", "url": "https://alfabank.ru/get-money/credit/credit-cash/"},
        {"name": "ОТП Банк", "url": "https://www.otpbank.ru/retail/credits/cash/moscow/"},
        {"name": "ВТБ", "url": "https://www.vtb.ru/personal/kredit/moskva/"},
    ],
}

# =========================
# UI
# =========================

st.set_page_config(page_title="Battle Cards")

st.title("Баттл-карты (Yandex GPT + парсинг)")

api_key = st.text_input("Yandex API Key", type="password")
folder_id = st.text_input("Folder ID")

battle_card_type = st.selectbox(
    "Тип баттл-карты",
    list(PRODUCT_BANK_URLS.keys())
)

banks = PRODUCT_BANK_URLS[battle_card_type]

selected = st.multiselect(
    "Банки",
    [b["name"] for b in banks],
    default=[b["name"] for b in banks]
)

model = f"gpt://{folder_id}/gpt-oss-120b/latest" if folder_id else None

# =========================
# HTTP HELPERS
# =========================

def fetch_html(url: str) -> str:
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text


def clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)

# =========================
# YANDEX GPT CALL
# =========================

def call_yandex_gpt(prompt: str):
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
        "x-folder-id": folder_id
    }

    payload = {
        "modelUri": model,
        "completionOptions": {
            "stream": False,
            "temperature": 0.0,
            "maxTokens": 2500
        },
        "messages": [
            {
                "role": "system",
                "text": "Ты банковский аналитик. Работаешь строго по тексту. Не выдумываешь данные."
            },
            {
                "role": "user",
                "text": prompt
            }
        ]
    }

    r = requests.post(url, json=payload, headers=headers, timeout=60)
    r.raise_for_status()

    return r.json()["result"]["alternatives"][0]["message"]["text"]

# =========================
# SCHEMA
# =========================

def get_schema(battle_card_type: str):
    # оставлено без упрощения логики
    return """
## Основные параметры кредита
| Параметр | Содержание |
|---|---|
| Название банка | |
| URL источника | |
| Название продукта | |
| Процентная ставка | |
| ПСК | |
| Максимальная сумма | |
| Минимальная сумма | |
| Срок | |
| График платежей | |
"""

# =========================
# EXTRACTION PER BANK
# =========================

def extract_bank(text, bank_name, url, schema):
    prompt = f"""
Тип баттл-карты:
{schema}

Банк:
{bank_name}

Источник:
{url}

Текст:
{text}

Правила:
- только факты из текста
- если нет данных: "Не указано"
- не придумывать
- вернуть Markdown таблицу
"""

    return call_yandex_gpt(prompt)

# =========================
# MERGE STEP (GLOBAL TABLE)
# =========================

def merge_tables(tables: list[str]):
    prompt = f"""
У тебя есть несколько таблиц по разным банкам.

Задача:
1. объединить в одну сравнительную таблицу
2. строки = параметры
3. столбцы = банки
4. ничего не придумывать
5. сохранить все числа и ставки

ТАБЛИЦЫ:
{chr(10).join(tables)}

Верни ОДНУ Markdown таблицу.
"""

    return call_yandex_gpt(prompt)

# =========================
# RUN
# =========================

if st.button("Запустить парсинг"):

    if not api_key or not folder_id:
        st.error("Нужны API Key и Folder ID")
        st.stop()

    schema = get_schema(battle_card_type)

    selected_banks = [b for b in banks if b["name"] in selected]

    results = []

    for b in selected_banks:
        st.write(f"Парсинг: {b['name']}")

        html = fetch_html(b["url"])
        text = clean_text(html)

        table = extract_bank(text, b["name"], b["url"], schema)

        results.append(table)

    st.write("### Объединённая таблица")

    final = merge_tables(results)

    st.markdown(final)
