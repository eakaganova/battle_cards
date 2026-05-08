import streamlit as st
import time
import traceback
import openai

# =========================
# CONFIG
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
    "Кредит наличными": [
        {"name": "Сбер", "url": "https://www.sberbank.ru"},
        {"name": "ВТБ", "url": "https://www.vtb.ru"},
    ]
}

# =========================
# YANDEX LLM
# =========================

YANDEX_FOLDER = "b1gd45ibb82t3i8g80fn"
YANDEX_API_KEY = "AQVNz6Uc8mdhGauttpxIdJdvtF6S2KZzZwm8w08J"
YANDEX_MODEL = "gpt-oss-120b/latest"

client = openai.OpenAI(
    api_key=YANDEX_API_KEY,
    base_url="https://ai.api.cloud.yandex.net/v1",
    project=YANDEX_FOLDER
)

# =========================
# STREAMLIT STATE
# =========================

st.set_page_config(page_title="Battle Cards", layout="wide")

if "logs" not in st.session_state:
    st.session_state.logs = []

if "status" not in st.session_state:
    st.session_state.status = "Idle"

# =========================
# LOGGING
# =========================

def log(msg):
    ts = time.strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{ts}] {msg}")

def render_logs():
    st.subheader("Логи")
    st.code("\n".join(st.session_state.logs[-300:]))

# =========================
# STATUS
# =========================

status_box = st.empty()

def set_status(msg):
    st.session_state.status = msg
    status_box.info(f"Статус: {msg}")

# =========================
# PROMPT ENGINE (ВАЖНО)
# =========================

def get_structure(battle_card_type):
    if battle_card_type == "КНЗ: кредит под залог недвижимости":
        return """
## Основные параметры кредита
| Параметр | Содержание |
|---|---|
| Название банка | |
| URL источника | |
| Процентная ставка | |
| Максимальная сумма кредита | |
| Минимальная сумма кредита | |
| Срок | |
| LTV | |
| Страхование | |
"""

    if battle_card_type == "КНА: кредит под залог автомобиля":
        return """
## Основные параметры кредита
| Параметр | Содержание |
|---|---|
| Название банка | |
| URL источника | |
| Процентная ставка | |
| ПСК | |
| Срок | |
| Максимальная сумма | |

## Залог
| Параметр | Содержание |
|---|---|
| Требуется ли авто в залог | |
| LTV | |
| Ограничения | |
"""

    return """
## Параметры
| Параметр | Содержание |
|---|---|
"""

def build_prompt(battle_card_type, bank, url, text):
    structure = get_structure(battle_card_type)

    return f"""
ТИП: {battle_card_type}
БАНК: {bank}
URL: {url}

ПРАВИЛА:
- Используй только текст
- Не додумывай
- Если нет данных → "Не указано"
- Если косвенно → "упоминается косвенно"

СТРУКТУРА:
{structure}

ИСТОЧНИК:
{text}
"""

# =========================
# SAFE LLM PARSE
# =========================

def extract_text(response):
    try:
        if hasattr(response, "output_text") and response.output_text:
            return response.output_text

        if hasattr(response, "output") and response.output:
            for item in response.output:
                if hasattr(item, "content") and item.content:
                    for c in item.content:
                        if hasattr(c, "text") and c.text:
                            return c.text
    except Exception:
        return None

    return None

# =========================
# PIPELINE
# =========================

def run_pipeline(battle_card_type, banks):
    try:
        st.session_state.logs = []
        set_status("Запуск")

        results = []

        for bank in banks:
            try:
                set_status(f"Парсинг {bank['name']}")
                log(f"Start: {bank['name']}")

                # пока без HTML-скрейпинга (URL как placeholder)
                text = bank["url"]

                log(f"Input size: {len(text)}")

                prompt = build_prompt(
                    battle_card_type,
                    bank["name"],
                    bank["url"],
                    text
                )

                log(f"Prompt size: {len(prompt)}")

                response = client.responses.create(
                    model=f"gpt://{YANDEX_FOLDER}/{YANDEX_MODEL}",
                    temperature=0.3,
                    input=prompt,
                    max_output_tokens=2000
                )

                log("LLM response received")

                result = extract_text(response)

                if not result:
                    log(f"EMPTY OUTPUT: {bank['name']}")
                    log(str(response))
                    continue

                results.append(result)

            except Exception:
                log(f"ERROR bank: {bank['name']}")
                log(traceback.format_exc())

        if not results:
            log("NO RESULTS GENERATED")
            return None

        final = "\n\n---\n\n".join(results)

        set_status("Готово")
        return final

    except Exception:
        log("PIPELINE CRASH")
        log(traceback.format_exc())
        return None

# =========================
# UI
# =========================

st.title("Battle Cards (Yandex LLM)")

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

selected_banks = [b for b in banks if b["name"] in selected]

if st.button("Запустить"):
    result = run_pipeline(battle_card_type, selected_banks)

    if result:
        st.success("Готово")
        st.markdown(result)
    else:
        st.error("Пустой результат — смотри логи")

render_logs()
