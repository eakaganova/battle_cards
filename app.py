import streamlit as st
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

URL = "https://www.tbank.ru/travel/"

st.title("Парсер + LLM")

# ключ лучше хранить через Streamlit secrets или env
YANDEX_CLOUD_FOLDER = st.text_input("Folder ID")
YANDEX_API_KEY = st.text_input("API Key", type="password")

MODEL = "gpt://b1gd45ibb82t3i8g80fn/gpt-oss-120b/latest"


def get_llm_client(api_key: str, folder: str):
    return OpenAI(
        api_key=api_key,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=folder
    )


if st.button("Собрать и проанализировать"):
    try:
        # 1. Парсим страницу
        r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.encoding = "utf-8"

        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)[:2000]  # ограничим для LLM

        st.subheader("Сырой текст (обрезка)")
        st.code(text[:200])

        # 2. LLM запрос
        if not (YANDEX_API_KEY and YANDEX_CLOUD_FOLDER):
            st.warning("Введите API key и Folder ID")
            st.stop()

        client = get_llm_client(YANDEX_API_KEY, YANDEX_CLOUD_FOLDER)

        response = client.responses.create(
            model=MODEL,
            temperature=0.3,
            max_output_tokens=500,
            instructions="Ты аналитик. Кратко опиши, что за сервис на странице.",
            input=text
        )

        st.subheader("Ответ LLM")
        st.write(response.output_text)

    except Exception as e:
        st.error("Ошибка")
        st.exception(e)
