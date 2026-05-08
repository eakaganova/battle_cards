import streamlit as st
import openai
import json

# =========================
# DATA SOURCES
# =========================

PRODUCT_BANK_URLS = {
    "КНЗ: кредит под залог недвижимости": [
        {"name": "Сбер", "url": "https://www.sberbank.ru/ru/person/credits/money/credit_zalog"},
        {"name": "ВТБ", "url": "https://www.vtb.ru/personal/ipoteka/ipoteka-pod-zalog-nedvizhimosti/"},
        {"name": "Совкомбанк", "url": "https://sovcombank.ru/credits/cash/alternativa"},
        {"name": "МТС Банк", "url": "https://www.mtsbank.ru/chastnim-licam/ipoteka/kredit-pod-zalog/"},
        {"name": "Газпромбанк", "url": "https://www.gazprombank.ru/personal/bail/pod-zalog/"},
        {"name": "Альфа-Банк", "url": "https://alfabank.ru/get-money/credit/pod-zalog/"},
    ]
}

# =========================
# YANDEX LLM CONFIG (ВАШ СТАНДАРТ)
# =========================

YANDEX_CLOUD_FOLDER = "b1gd45ibb82t3i8g80fn"
YANDEX_CLOUD_API_KEY = "AQVNz6Uc8mdhGauttpxIdJdvtF6S2KZzZwm8w08J"  # из UI
YANDEX_CLOUD_MODEL = "gpt-oss-120b/latest"

client = None

def init_client(api_key: str):
    global client
    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_CLOUD_FOLDER
    )

# =========================
# STREAMLIT UI
# =========================

st.set_page_config(page_title="Battle Cards", layout="wide")

st.title("Battle Cards — Extract + Normalize Pipeline")

api_key = st.text_input("Yandex API Key", type="password")

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
# INIT CLIENT
# =========================

if api_key and not client:
    init_client(api_key)

# =========================
# 1. EXTRACTION PROMPT (JSON ONLY)
# =========================

def build_extraction_prompt(battle_card_type, bank_name, url, text):
    return f"""
Ты извлекаешь структурированные данные из банковского текста.

ВАЖНО:
- Верни ТОЛЬКО JSON
- Без Markdown
- Без комментариев
- Если нет данных → null

ФОРМАТ:

{{
  "bank": "{bank_name}",
  "url": "{url}",
  "product_type": "{battle_card_type}",
  "rate_min": null,
  "rate_max": null,
  "psk": null,
  "loan_term_min": null,
  "loan_term_max": null,
  "ltv": null,
  "max_amount": null,
  "min_amount": null,
  "fees": [],
  "requirements": [],
  "insurance": null,
  "notes": null
}}

ТЕКСТ:
{text}
"""

# =========================
# LLM CALL (ВАШ FORMAT)
# =========================

def call_llm(prompt: str):
    try:
        response = client.responses.create(
            model=f"gpt://{YANDEX_CLOUD_FOLDER}/{YANDEX_CLOUD_MODEL}",
            temperature=0.2,
            instructions="Ты строго извлекаешь данные в JSON формате. Без текста.",
            input=prompt,
            max_output_tokens=2000
        )

        return response.output_text

    except Exception as e:
        return None

# =========================
# PARSE JSON SAFE
# =========================

def safe_json_parse(text):
    try:
        if not text:
            return None
        return json.loads(text)
    except:
        return None

# =========================
# NORMALIZATION LAYER
# =========================

def normalize(item):
    if not item:
        return None

    return {
        "bank": item.get("bank"),
        "url": item.get("url"),
        "rate_min": item.get("rate_min"),
        "rate_max": item.get("rate_max"),
        "psk": item.get("psk"),
        "loan_term_min": item.get("loan_term_min"),
        "loan_term_max": item.get("loan_term_max"),
        "ltv": item.get("ltv"),
        "max_amount": item.get("max_amount"),
        "fees_count": len(item.get("fees", []) or []),
        "notes": item.get("notes")
    }

# =========================
# AGGREGATION TABLE
# =========================

def render_table(data):
    st.subheader("Сравнительная баттл-таблица")

    st.table([
        {
            "Банк": d["bank"],
            "Ставка мин": d["rate_min"],
            "Ставка макс": d["rate_max"],
            "ПСК": d["psk"],
            "Срок мин": d["loan_term_min"],
            "Срок макс": d["loan_term_max"],
            "LTV": d["ltv"],
            "Макс сумма": d["max_amount"],
            "Кол-во комиссий": d["fees_count"]
        }
        for d in data if d
    ])

# =========================
# PIPELINE EXECUTION
# =========================

if st.button("Запустить анализ"):

    if not client:
        st.error("Нет API ключа")
        st.stop()

    results = []

    for bank in banks:
        if bank["name"] not in selected:
            continue

        url = bank["url"]

        # пока заглушка (позже заменишь на HTML parser)
        fake_text = f"Страница банка {bank['name']} {url}"

        prompt = build_extraction_prompt(
            battle_card_type,
            bank["name"],
            url,
            fake_text
        )

        raw = call_llm(prompt)
        parsed = safe_json_parse(raw)
        normalized = normalize(parsed)

        results.append(normalized)

    render_table(results)
