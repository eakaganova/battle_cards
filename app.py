import streamlit as st
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

URL = "https://www.tbank.ru/travel/"

st.set_page_config(page_title="Parser + LLM")

st.title("Парсер + LLM анализ")

st.write("Собирает текст со страницы и отправляет в LLM")


# -----------------------
# INPUT
# -----------------------

api_key = st.text_input("API Key (Yandex Cloud)", type="password")
folder_id = st.text_input("Folder ID")

model = f"gpt://{folder_id}/gpt-oss-120b/latest" if folder_id else ""


# -----------------------
# CLIENT
# -----------------------

def get_client(api_key: str, folder_id: str):
    return OpenAI(
        api_key=api_key,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=folder_id
    )


# -----------------------
# SAFE LLM PARSE
# -----------------------

def extract_text(response) -> str:
    """
    Безопасное извлечение текста из Yandex/OpenAI Responses API
    """
    try:
        # основной вариант
        return response.output[0].content[0].text
    except Exception:
        pass

    try:
        # fallback 1
        return response.output_text
    except Exception:
        pass

    try:
        # fallback 2 — полный dump
        return str(response.output)
    except Exception:
        return "Не удалось извлечь ответ LLM"


# -----------------------
# SCRAPER
# -----------------------

def scrape_text(url: str) -> str:
    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20
    )

    # фикс кракозябр
    r.encoding = r.apparent_encoding

    soup = BeautifulSoup(r.text, "html.parser")

    text = soup.get_text(" ", strip=True)

    return text[:3000]


# -----------------------
# RUN
# -----------------------

if st.button("Запустить"):

    if not api_key or not folder_id:
        st.error("Нужны API key и folder_id")
        st.stop()

    if not model:
        st.error("folder_id пустой → модель не собрана")
        st.stop()

    try:
        st.subheader("1. Парсинг сайта")

        text = scrape_text(URL)

        st.code(text[:300])

        st.subheader("2. Отправка в LLM")

        client = get_client(api_key, folder_id)

        prompt = """
Ты аналитик продукта.

На основе текста:
1. Определи, что это за сервис
2. Перечисли 5 ключевых функций
3. Кратко опиши ценность

Верни результат в виде таблицы:
| Пункт | Ответ |
"""

        response = client.responses.create(
            model=model,
            temperature=0.3,
            max_output_tokens=500,
            instructions=prompt,
            input=text
        )

        result = extract_text(response)

        st.subheader("Результат LLM")
        st.write(result)

    except Exception as e:
        st.error("Ошибка выполнения")
        st.exception(e)
