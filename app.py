import streamlit as st
import openai

# =========================
# CONFIG: BANK LINKS
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
# STREAMLIT UI
# =========================

st.set_page_config(page_title="Battle Cards", layout="wide")

st.title("Баттл-карты (Yandex LLM + парсинг ссылок)")

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

# =========================
# YANDEX CLIENT
# =========================

YANDEX_CLOUD_MODEL = "gpt-oss-120b/latest"

def get_client():
    return openai.OpenAI(
        api_key=api_key,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=folder_id
    )

client = None
if api_key and folder_id:
    client = get_client()

# =========================
# PROMPT BUILDER (СТРОГИЙ)
# =========================

def build_prompt(battle_card_type, bank_name, url, text):
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
        "Не удаляй числовые параметры (ставки, сроки, суммы, LTV, ПСК).\n"
        "Верни результат строго в Markdown.\n\n"
        f"Текст:\n{text}"
    )

# =========================
# LLM CALL (YANDEX RESPONSES API)
# =========================

def call_llm(prompt: str) -> str:
    try:
        response = client.responses.create(
            model=f"gpt://{folder_id}/{YANDEX_CLOUD_MODEL}",
            temperature=0.3,
            instructions="Ты строгий аналитик банковских продуктов. Не выдумывай данные.",
            input=prompt,
            max_output_tokens=2000
        )

        return response.output_text or "Пустой ответ модели"

    except Exception as e:
        return f"Ошибка LLM: {str(e)}"

# =========================
# BANK FILTER
# =========================

def get_selected_sources():
    return [
        b for b in banks
        if b["name"] in selected
    ]

# =========================
# MAIN ACTION
# =========================

if st.button("Сформировать общую таблицу"):

    if not client:
        st.error("Введите API Key и Folder ID")
        st.stop()

    sources = get_selected_sources()

    if not sources:
        st.error("Не выбраны банки")
        st.stop()

    results = []

    for bank in sources:
        url = bank["url"]

        # TODO: сюда позже вставим реальный HTML-парсинг
        fake_text = f"Содержимое страницы: {bank['name']} ({url})"

        prompt = build_prompt(
            battle_card_type,
            bank["name"],
            url,
            fake_text
        )

        result = call_llm(prompt)

        results.append({
            "bank": bank["name"],
            "url": url,
            "result": result
        })

    # =========================
    # GLOBAL TABLE (ОДНА)
    # =========================

    st.subheader("Общая баттл-таблица")

    output = ""

    for r in results:
        output += f"\n\n---\n\n## {r['bank']}\n"
        output += f"Источник: {r['url']}\n\n"
        output += r["result"]

    st.markdown(output)
