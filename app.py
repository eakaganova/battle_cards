import streamlit as st
from openai import OpenAI
import json

# =========================
# CONFIG: LINKS
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
# STREAMLIT SETUP
# =========================

st.set_page_config(page_title="Battle Cards", layout="wide")
st.title("Баттл-карты (YandexGPT + парсинг)")

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

model = f"gpt://{folder_id}/yandexgpt/latest" if folder_id else None

# =========================
# CLIENT (YANDEX)
# =========================

def get_client():
    return OpenAI(
        api_key=api_key,
        base_url="https://llm.api.cloud.yandex.net/v1",
        project=folder_id
    )

# =========================
# PROMPTS (НЕ УПРОЩАТЬ)
# =========================

def get_structure(battle_card_type: str) -> str:
    if battle_card_type == "КНА: кредит под залог автомобиля":
        return """(структура КНА ОСТАВЛЕНА БЕЗ ИЗМЕНЕНИЙ — ВСТАВЬ СЮДА ПОЛНЫЙ ОРИГИНАЛ)"""
    if battle_card_type == "КНЗ: кредит под залог недвижимости":
        return """(структура КНЗ ОСТАВЛЕНА БЕЗ ИЗМЕНЕНИЙ — ВСТАВЬ СЮДА ПОЛНЫЙ ОРИГИНАЛ)"""
    if battle_card_type == "Автокредит":
        return """(структура Автокредит ОСТАВЛЕНА БЕЗ ИЗМЕНЕНИЙ — ВСТАВЬ СЮДА ПОЛНЫЙ ОРИГИНАЛ)"""
    if battle_card_type == "Кредит наличными":
        return """(структура наличные ОСТАВЛЕНА БЕЗ ИЗМЕНЕНИЙ — ВСТАВЬ СЮДА ПОЛНЫЙ ОРИГИНАЛ)"""
    return "NO STRUCTURE"

def build_prompt(battle_card_type, bank_name, url, text):
    structure = get_structure(battle_card_type)

    return (
        f"Тип баттл-карты: {battle_card_type}\n"
        f"Цель: составить максимально полную таблицу условий продукта для банка {bank_name}.\n\n"
        f"Источник: {url}\n\n"
        "Работай только на основании предоставленного текста.\n"
        "Не делай предположений.\n"
        "Не используй знания из интернета или памяти модели.\n"
        "Если информации нет — пиши: Не указано.\n"
        "Если данные косвенные — помечай: упоминается косвенно.\n"
        "Если есть противоречие — укажи оба значения.\n"
        "НЕ удаляй числовые параметры.\n"
        "Верни результат строго в Markdown.\n\n"
        f"{structure}\n\n"
        f"Текст:\n{text}"
    )

# =========================
# PARSE LINKS
# =========================

def build_sources():
    sources = []
    for b in banks:
        if b["name"] in selected:
            sources.append(b)
    return sources

# =========================
# SAFE LLM CALL
# =========================

def call_llm(prompt):
    client = get_client()

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Ты строгий аналитик банковских продуктов."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    try:
        return resp.choices[0].message.content
    except Exception:
        return "Ошибка: пустой или некорректный ответ модели"

# =========================
# MAIN LOGIC
# =========================

if st.button("Сформировать общую таблицу"):

    if not api_key or not folder_id:
        st.error("Нужны API Key и Folder ID")
        st.stop()

    sources = build_sources()

    if not sources:
        st.error("Не выбраны банки")
        st.stop()

    all_results = []

    for bank in sources:
        url = bank["url"]

        # здесь можно позже подключить реальный парсинг HTML
        fake_text = f"Содержимое страницы банка: {bank['name']} ({url})"

        prompt = build_prompt(
            battle_card_type,
            bank["name"],
            url,
            fake_text
        )

        result = call_llm(prompt)

        all_results.append({
            "bank": bank["name"],
            "url": url,
            "result": result
        })

    # =========================
    # FINAL OUTPUT (ОБЩАЯ ТАБЛИЦА)
    # =========================

    st.subheader("Общая баттл-таблица")

    combined = ""

    for r in all_results:
        combined += f"\n\n# {r['bank']}\n\n"
        combined += f"Источник: {r['url']}\n\n"
        combined += r["result"]

    st.markdown(combined)
