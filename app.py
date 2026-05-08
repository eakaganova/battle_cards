import json
import os
import re
import time
import traceback
from typing import Any

import openai
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# =========================
# CONFIG
# =========================

PRODUCT_BANK_URLS = {
    "КНЗ: кредит под залог недвижимости":[
        {"name": "Сбер", "url": "https://www.sberbank.ru/ru/person/credits/money/credit_zalog"},
        {"name": "ВТБ", "url": "https://www.vtb.ru/personal/ipoteka/ipoteka-pod-zalog-nedvizhimosti/"},
        {"name": "Совкомбанк", "url": "https://sovcombank.ru/credits/cash/alternativa"},
        {"name": "МТС Банк", "url": "https://www.mtsbank.ru/chastnim-licam/ipoteka/kredit-pod-zalog/"},
        {"name": "Газпромбанк", "url": "https://www.gazprombank.ru/personal/bail/pod-zalog/"},
        {"name": "Альфа-Банк", "url": "https://alfabank.ru/get-money/credit/pod-zalog/"},
    ],
    "КНА: кредит под залог автомобиля":[
        {"name": "Т-Банк", "url": "https://www.tbank.ru/loans/cash-loan/auto/"},
        {"name": "Совкомбанк", "url": "https://sovcombank.ru/credits/cash/pod-zalog-avto-"},
        {"name": "ВТБ", "url": "https://www.vtb.ru/personal/kredit/pod-zalog-avto/"},
    ],
    "Кредит наличными":[
        {"name": "Сбер", "url": "https://www.sberbank.ru"},
        {"name": "ВТБ", "url": "https://www.vtb.ru"},
    ],
}

PARAMETER_SETS = {
    "КНЗ: кредит под залог недвижимости":["URL источника", "Процентная ставка", "ПСК", "Максимальная сумма кредита", "Минимальная сумма кредита", "Срок", "LTV / доля от стоимости недвижимости", "Обеспечение / объект залога", "Страхование", "Требования к заёмщику", "Требования к недвижимости", "Подтверждение дохода", "Способ получения денег", "Досрочное погашение", "Комиссии", "Особые условия / ограничения", "Документы", "Как оформить", "Что не указано на странице", "Статус парсинга"],
    "КНА: кредит под залог автомобиля":["URL источника", "Процентная ставка", "ПСК", "Максимальная сумма", "Минимальная сумма", "Срок", "Требуется ли авто в залог", "LTV / доля от стоимости автомобиля", "Кто может пользоваться автомобилем", "Требования к автомобилю", "Требования к заёмщику", "Подтверждение дохода", "Страхование", "Комиссии", "Документы", "Как оформить", "Особые условия / ограничения", "Что не указано на странице", "Статус парсинга"],
    "Кредит наличными":["URL источника", "Процентная ставка", "ПСК", "Сумма", "Срок", "Требования к заёмщику", "Документы", "Страхование", "Комиссии", "Как оформить", "Что не указано на странице", "Статус парсинга"],
}

# =========================
# ENV
# =========================
YANDEX_FOLDER = os.getenv("YANDEX_FOLDER")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_MODEL = os.getenv("YANDEX_MODEL", "gpt-oss-120b/latest")

st.set_page_config(page_title="Battle Cards", layout="wide")

# =========================
# SESSION STATE
# =========================
defaults = {
    "logs":[],
    "status": "Ожидание запуска",
    "progress_value": 0,
    "progress_text": "Выберите режим и параметры.",
    "current_bank": "—",
    "current_step": "—",
    "completed_banks": 0,
    "total_banks": 0,
    "user_updates": [],
    "custom_params_list":["Процентная ставка", "ПСК", "Сумма", "Срок", "Требования"]
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =========================
# LOGGING / UI
# =========================
def log(message: str) -> None:
    st.session_state.logs.append(f"[{time.strftime('%H:%M:%S')}] {message}")

def add_user_update(message: str) -> None:
    st.session_state.user_updates.append(f"[{time.strftime('%H:%M:%S')}] {message}")

def update_runtime_ui(status=None, step=None, bank=None, progress=None, user_message=None):
    if status: st.session_state.status = status
    if step: st.session_state.current_step = step
    if bank: st.session_state.current_bank = bank
    if progress is not None: st.session_state.progress_value = progress
    if user_message: add_user_update(user_message)

def render_runtime_panel():
    st.info(st.session_state.status)
    st.progress(st.session_state.progress_value, text=f"{st.session_state.progress_value}%")
    col1, col2, col3 = st.columns(3)
    col1.metric("Банк", st.session_state.current_bank)
    col2.metric("Этап", st.session_state.current_step)
    col3.metric("Прогресс", f"{st.session_state.completed_banks} / {st.session_state.total_banks}")
    with st.expander("Ход процесса", expanded=True):
        for item in st.session_state.user_updates[-10:]: st.write(item)

# =========================
# PARSERS (Requests / Playwright)
# =========================
def fetch_text_playwright(url: str) -> str:
    # (Сокращено для краткости - используйте вашу оригинальную функцию fetch_text_playwright)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        text = page.locator("body").inner_text()
        browser.close()
        return text

def get_page_text(url: str, bank_name: str) -> str:
    try:
        # Попытка через requests
        res = requests.get(url, timeout=10)
        text = BeautifulSoup(res.text, "html.parser").get_text("\n")
        if len(text) > 1000: return text
    except: pass
    return fetch_text_playwright(url)

# =========================
# LLM LOGIC
# =========================
client = openai.OpenAI(api_key=YANDEX_API_KEY, base_url="https://ai.api.cloud.yandex.net/v1", project=YANDEX_FOLDER) if YANDEX_FOLDER and YANDEX_API_KEY else None

def call_llm(prompt: str):
    return client.responses.create(model=f"gpt://{YANDEX_FOLDER}/{YANDEX_MODEL}", input=prompt, temperature=0.1)

def build_extraction_prompt(bank_name, url, source_text, params):
    return f"Банк: {bank_name}\nURL: {url}\nПараметры: {json.dumps(params)}\nТекст: {source_text}\nВерни JSON с этими ключами. Если нет данных - 'Не указано'."

# =========================
# PIPELINE
# =========================
def run_pipeline(selected_banks, params):
    records =[]
    st.session_state.total_banks = len(selected_banks)
    for i, bank in enumerate(selected_banks):
        update_runtime_ui(bank=bank['name'], status=f"Анализ {bank['name']}", progress=int((i/len(selected_banks))*100))
        text = get_page_text(bank['url'], bank['name'])
        resp = call_llm(build_extraction_prompt(bank['name'], bank['url'], text[:15000], params))
        
        # Парсинг JSON ответа... (упрощенно)
        try:
            parsed = json.loads(resp.output_text.replace("```json", "").replace("```", ""))
            parsed["Банк"] = bank['name']
            records.append(parsed)
        except: pass
        st.session_state.completed_banks += 1
    return pd.DataFrame(records)

# =========================
# UI MAIN
# =========================
st.title("Battle Cards Generator")
mode = st.radio("Режим", ["Быстрый", "Расширенный"], horizontal=True)

if mode == "Быстрый":
    cat = st.selectbox("Тип продукта", list(PRODUCT_BANK_URLS.keys()))
    banks = PRODUCT_BANK_URLS[cat]
    params = PARAMETER_SETS[cat]
else:
    st.subheader("Конструктор")
    new_p = st.text_input("Добавить параметр")
    if st.button("Добавить в список") and new_p:
        st.session_state.custom_params_list.append(new_p)
    params = st.multiselect("Выберите параметры", st.session_state.custom_params_list, default=st.session_state.custom_params_list)
    banks =[]
    for group in PRODUCT_BANK_URLS.values(): banks.extend(group)
    # Убираем дубликаты банков
    banks = {b['name']: b for b in banks}.values()

selected_names = st.multiselect("Банки", [b['name'] for b in banks], default=[b['name'] for b in banks])
selected_banks = [b for b in banks if b['name'] in selected_names]

render_runtime_panel()

if st.button("Запустить"):
    df = run_pipeline(selected_banks, params)
    st.write("Результаты:", df)
    st.download_button("Скачать CSV", df.to_csv().encode('utf-8'), "data.csv")
