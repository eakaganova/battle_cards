import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential
from openai import OpenAI

# =========================
# CONFIG
# =========================

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

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
# LLM SCHEMA PROMPTS (НЕ УПРОЩЕНЫ)
# =========================

def get_schema(battle_card_type: str):
    # твои промты сохранены 1:1
    if battle_card_type == "КНА: кредит под залог автомобиля":
        return """## Основные параметры кредита
| Параметр | Содержание |
|---|---|
| Название банка | |
| URL источника | |
| Название продукта | |
| Тип кредита | |
| Процентная ставка | |
| Полная стоимость кредита / ПСК | |
| Максимальная сумма кредита | |
| Минимальная сумма кредита | |
| Максимальный срок кредитования | |
| Минимальный срок кредитования | |
| Валюта кредита | |
| График платежей | |
| Целевое / нецелевое использование средств | |

## Залоговое обеспечение
| Параметр | Содержание |
|---|---|
| Требуется ли залог автомобиля | |
| Какие транспортные средства принимаются в залог | |
| Легковые автомобили | |
| Коммерческий транспорт | |
| Мототехника | |
| Иностранные / отечественные автомобили | |
| Максимальный возраст автомобиля | |
| Требования к техническому состоянию | |
| Требования к регистрации автомобиля | |
| Требования к собственнику автомобиля | |
| Возможность залога автомобиля третьего лица | |
| Максимальный LTV | |
| Оценка автомобиля | |
| Ограничения использования | |
"""

    if battle_card_type == "КНЗ: кредит под залог недвижимости":
        return """## Основные параметры кредита
| Параметр | Содержание |
|---|---|
| Название банка | |
| URL источника | |
| Название продукта | |
| Процентная ставка | |
| Максимальная сумма кредита | |
| Минимальная сумма кредита | |
| Максимальный срок кредитования | |
| Минимальный срок кредитования | |
| График платежей | |
| Целевое использование средств | |
| LTV | |
"""

    return "## Универсальная таблица\n| Параметр | Содержание |\n|---|---|\n"

# =========================
# PARSER
# =========================

def fetch_html(url: str) -> str:
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    return r.text

def clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)

# =========================
# LLM EXTRACTION (per bank)
# =========================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def extract_bank(text: str, bank_name: str, url: str, schema: str):
    prompt = f"""
Тип баттл-карты:
{schema}

Источник:
{url}

Банк:
{bank_name}

Текст:
{text}

Правила:
- не фантазируй
- если нет данных: "Не указано"
- сохраняй числа, ставки, сроки
- строго Markdown таблица
"""

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "Ты банковский аналитик. Работаешь строго по данным."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    return resp.choices[0].message.content

# =========================
# AGGREGATION STEP (КЛЮЧЕВОЕ ИЗМЕНЕНИЕ)
# =========================

def merge_tables(all_tables: list[str]) -> str:
    prompt = f"""
У тебя есть несколько Markdown таблиц по разным банкам.

Твоя задача:
1. объединить их в одну сравнительную таблицу
2. выровнять параметры
3. сохранить все числовые значения
4. если значение отсутствует — "Не указано"
5. не придумывать данные

ТАБЛИЦЫ:
{chr(10).join(all_tables)}

Верни ОДНУ Markdown таблицу:
строки = параметры
колонки = банки
"""

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "Ты эксперт по банковскому сравнению продуктов."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    return resp.choices[0].message.content

# =========================
# STREAMLIT APP
# =========================

st.title("Банковский парсер баттл-карт")

battle_card_type = st.selectbox("Тип продукта", list(PRODUCT_BANK_URLS.keys()))

if st.button("Запустить парсинг"):

    schema = get_schema(battle_card_type)
    banks = PRODUCT_BANK_URLS[battle_card_type]

    st.write(f"Банков: {len(banks)}")

    extracted_tables = []

    for b in banks:
        st.write(f"Парсинг: {b['name']}")

        html = fetch_html(b["url"])
        text = clean_text(html)

        table = extract_bank(text, b["name"], b["url"], schema)

        extracted_tables.append(table)

    st.write("### Объединение таблиц...")

    final_table = merge_tables(extracted_tables)

    st.markdown(final_table)
