import streamlit as st
import requests
from bs4 import BeautifulSoup

URL = "https://www.tbank.ru/travel/"

st.title("Простой парсер страницы")

if st.button("Собрать текст"):
    try:
        response = requests.get(
            URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20
        )

        # КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ
        response.encoding = "utf-8"

        html = response.text

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True)

        st.write("Первые 100 символов:")
        st.code(text[:100])

    except Exception as e:
        st.error("Ошибка при запросе страницы")
        st.exception(e)
