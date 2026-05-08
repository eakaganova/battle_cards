import streamlit as st
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

URL = "https://www.tbank.ru/travel/"

st.title("Парсер + LLM (MVP)")

# -----------------------
# INPUT
# -----------------------

api_key = st.text_input("Yandex API Key", type="password")
folder_id = st.text_input("Folder ID")

MODEL = "gpt://b1gd45ibb82t3i8g80fn/gpt-oss-120b/latest"


def get_client(api_key: str, folder_id: str):
    return OpenAI(
        api_key=api_key,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=folder_id
    )


# -----------------------
# PARSER
# -----------------------

def parse_page(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)

    # важно для твоей ошибки с кракозябрами
    r.encoding = "utf-8"

    soup = BeautifulSoup(r.text, "html.parser")

    # убираем мусорные теги
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(" ", strip=True)

    return text


# -----------------------
# LLM PROMPT (1 штука)
# -----------------------

PROMPT = """
Ты аналитик цифровых продуктов.

Тебе дан текст страницы сервиса.

Задача:
1. Определи, что это за сервис
2. Выдели ключевые функции
3. Сформируй таблицу

Формат таблицы строго:

| Параметр | Значение |
|---|---|
| Сервис | |
| Основное назначение | |
| Ключевые функции | |
| Целевая аудитория | |
| Основные сценарии использования | |

Если данных нет — пиши "Не указано".
Не добавляй лишний текст.
"""


# -----------------------
# RUN
# -----------------------

if st.button("Запуск"):

    if not api_key or not folder_id:
        st.error("Введите API key и folder_id")
        st.stop()

    # 1. Парсинг
    st.subheader("1. Парсинг страницы")

    text = parse_page(URL)

    st.write("Сырый текст (обрезка):")
    st.code(text[:500])

    # ограничиваем LLM
    text = text[:6000]

    # 2. LLM
    st.subheader("2. LLM анализ")

    client = get_client(api_key, folder_id)

    response = client.responses.create(
        model=MODEL,
        temperature=0.2,
        max_output_tokens=800,
        instructions=PROMPT,
        input=text
    )

    result = response.output[0].content[0].text

    st.subheader("Результат")
    st.markdown(result)
