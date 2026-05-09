# -*- coding: utf-8 -*-

import io
import json
import os
import re
import time
import traceback
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import docx
import openai
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from pypdf import PdfReader


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
    ],
}

PARAMETER_SETS = {
    "КНЗ: кредит под залог недвижимости": [
        "URL источника",
        "Процентная ставка",
        "ПСК",
        "Максимальная сумма кредита",
        "Минимальная сумма кредита",
        "Срок",
        "LTV / доля от стоимости недвижимости",
        "Обеспечение / объект залога",
        "Страхование",
        "Требования к заёмщику",
        "Требования к недвижимости",
        "Подтверждение дохода",
        "Способ получения денег",
        "Досрочное погашение",
        "Комиссии",
        "Особые условия / ограничения",
        "Документы",
        "Как оформить",
        "Что не указано на странице",
        "Статус парсинга",
    ],
    "КНА: кредит под залог автомобиля": [
        "URL источника",
        "Процентная ставка",
        "ПСК",
        "Максимальная сумма",
        "Минимальная сумма",
        "Срок",
        "Требуется ли авто в залог",
        "LTV / доля от стоимости автомобиля",
        "Кто может пользоваться автомобилем",
        "Требования к автомобилю",
        "Требования к заёмщику",
        "Подтверждение дохода",
        "Страхование",
        "Комиссии",
        "Документы",
        "Как оформить",
        "Особые условия / ограничения",
        "Что не указано на странице",
        "Статус парсинга",
    ],
    "Кредит наличными": [
        "URL источника",
        "Процентная ставка",
        "ПСК",
        "Сумма",
        "Срок",
        "Требования к заёмщику",
        "Документы",
        "Страхование",
        "Комиссии",
        "Как оформить",
        "Что не указано на странице",
        "Статус парсинга",
    ],
}

DEFAULT_CUSTOM_PARAMS = [
    "URL источника",
    "Цена / стоимость",
    "Тарифы",
    "Условия подключения",
    "Функциональность",
    "Ограничения",
    "Требования к клиенту",
    "Документы",
    "Как оформить / подключить",
    "Преимущества",
    "Что не указано на странице",
    "Статус парсинга",
]


INDUSTRY_PARAMETER_TEMPLATES = {
    "Свой список": DEFAULT_CUSTOM_PARAMS,
    "Банки / кредиты": DEFAULT_CUSTOM_PARAMS,
    "SaaS / CRM / IT-сервисы": [
        "URL источника", "Цена / тарифы", "Пробный период", "Основная функциональность",
        "Интеграции", "Ограничения тарифов", "Поддержка", "SLA", "Безопасность",
        "Документы", "Как подключить", "Преимущества", "Что не указано на странице", "Статус парсинга",
    ],
    "Страхование": [
        "URL источника", "Стоимость / тариф", "Страховое покрытие", "Исключения", "Франшиза",
        "Срок действия", "Требования к клиенту", "Документы", "Как оформить", "Преимущества",
        "Что не указано на странице", "Статус парсинга",
    ],
    "Маркетплейсы / e-commerce": [
        "URL источника", "Комиссии", "Логистика", "Выплаты", "Требования к продавцу",
        "Ограничения", "Поддержка", "Документы", "Как подключиться", "Преимущества",
        "Что не указано на странице", "Статус парсинга",
    ],
    "Доставка / логистика": [
        "URL источника", "Стоимость доставки", "Сроки доставки", "География",
        "Ограничения по весу / габаритам", "Условия подключения", "Интеграции",
        "Документы", "Поддержка", "Преимущества", "Что не указано на странице", "Статус парсинга",
    ],
}

LOW_CONFIDENCE_VALUES = {"низкая", "low", "средняя", "medium"}
META_COLUMN_SUFFIXES = ["Источник значения", "Фрагмент источника", "Уверенность", "Причина отсутствия"]


# =========================
# ENV / LLM SETTINGS
# =========================

YANDEX_FOLDER = os.getenv("YANDEX_FOLDER")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_MODEL = os.getenv("YANDEX_MODEL", "gpt-oss-120b/latest")

YANDEX_BASE_URL = "https://ai.api.cloud.yandex.net/v1"

MAX_SOURCE_CHARS = 60000
REQUESTS_TIMEOUT = 25
PLAYWRIGHT_TIMEOUT = 70000

MAX_DOCUMENT_FILES = 8
MAX_PDF_PAGES = 80
MAX_DOCUMENT_CHARS = 30000


# =========================
# STREAMLIT PAGE
# =========================

st.set_page_config(
    page_title="Battle Cards Generator",
    layout="wide",
)


# =========================
# SESSION STATE
# =========================

defaults = {
    "logs": [],
    "status": "Ожидание запуска",
    "progress_value": 0,
    "progress_text": "Выберите режим и параметры.",
    "current_company": "—",
    "current_step": "—",
    "completed_companies": 0,
    "total_companies": 0,
    "user_updates": [],
    "custom_params_text": "\n".join(DEFAULT_CUSTOM_PARAMS),
    "custom_companies": [
        {"name": "", "url": "", "manual_text": ""},
        {"name": "", "url": "", "manual_text": ""},
        {"name": "", "url": "", "manual_text": ""},
    ],
    "last_df": None,
    "last_meta_records": [],
    "last_raw_records": [],
    "last_comparison_insights": [],
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================
# LOGGING / STATE HELPERS
# =========================

def log(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{timestamp}] {message}")


def shorten_log_text(text: Any, limit: int = 220) -> str:
    text = clean_text(str(text or ""))
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def add_user_update(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    st.session_state.user_updates.append(f"[{timestamp}] {message}")


def update_runtime_state(
    status: Optional[str] = None,
    step: Optional[str] = None,
    company: Optional[str] = None,
    progress: Optional[int] = None,
    user_message: Optional[str] = None,
) -> None:
    if status is not None:
        st.session_state.status = status
    if step is not None:
        st.session_state.current_step = step
    if company is not None:
        st.session_state.current_company = company
    if progress is not None:
        progress = max(0, min(100, int(progress)))
        st.session_state.progress_value = progress
    if user_message:
        add_user_update(user_message)


def reset_runtime_state() -> None:
    st.session_state.logs = []
    st.session_state.status = "Запуск"
    st.session_state.progress_value = 0
    st.session_state.progress_text = "Подготовка"
    st.session_state.current_company = "—"
    st.session_state.current_step = "—"
    st.session_state.completed_companies = 0
    st.session_state.total_companies = 0
    st.session_state.user_updates = []
    st.session_state.last_df = None
    st.session_state.last_meta_records = []
    st.session_state.last_raw_records = []
    st.session_state.last_comparison_insights = []


# =========================
# LIVE STATUS UI
# =========================

def init_live_ui() -> Dict[str, Any]:
    return {
        "status_box": st.empty(),
        "progress_bar": st.empty(),
        "metrics_box": st.empty(),
        "steps_box": st.empty(),
        "events_box": st.empty(),
        "log_box": st.empty(),
    }


def render_live_status(
    ui: Dict[str, Any],
    status: str,
    step: str,
    company: str,
    progress: int,
    completed: int,
    total: int,
    started_at: float,
    last_event: str = "",
) -> None:
    elapsed = int(time.time() - started_at)
    minutes = elapsed // 60
    seconds = elapsed % 60

    progress = max(0, min(100, int(progress)))

    update_runtime_state(
        status=status,
        step=step,
        company=company,
        progress=progress,
        user_message=last_event if last_event else None,
    )

    ui["status_box"].info(
        f"**Статус:** {status}\n\n"
        f"**Сейчас:** {step}\n\n"
        f"**Объект:** {company}\n\n"
        f"**Последнее событие:** {last_event or '—'}\n\n"
        f"**Время выполнения:** {minutes:02d}:{seconds:02d}"
    )

    ui["progress_bar"].progress(progress, text=f"{progress}%")

    with ui["metrics_box"].container():
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Обработано", f"{completed} / {total}")
        col2.metric("Текущий этап", step)
        col3.metric("Текущий объект", company)
        col4.metric("Время", f"{minutes:02d}:{seconds:02d}")

    steps = [
        "Подготовка списка компаний и параметров",
        "Расширенный парсинг страницы",
        "Раскрытие скрытых блоков",
        "Сбор документов",
        "Обработка документов",
        "Использование ручного текста",
        "Извлечение параметров через LLM",
        "Нормализация записи",
        "Компания обработана",
        "Унификация общей таблицы",
        "Формирование файла",
        "Завершено",
    ]

    with ui["steps_box"].container():
        st.write("### Ход выполнения")
        for index, step_name in enumerate(steps, start=1):
            if step_name == step:
                st.write(f"▶️ **{index}. {step_name}**")
            else:
                st.write(f"▫️ {index}. {step_name}")

    with ui["events_box"].expander("Последние события", expanded=True):
        if st.session_state.user_updates:
            for item in st.session_state.user_updates[-12:]:
                st.write(item)
        else:
            st.write("Пока нет событий.")

    with ui["log_box"].expander("Технические логи", expanded=False):
        if st.session_state.logs:
            st.caption(f"Показаны последние {min(len(st.session_state.logs), 400)} из {len(st.session_state.logs)} записей.")
            for item in st.session_state.logs[-400:]:
                st.code(item)
        else:
            st.write("Пока нет логов.")


def render_static_runtime_panel() -> None:
    st.info(st.session_state.status)
    st.progress(
        st.session_state.progress_value,
        text=f"{st.session_state.progress_value}%",
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("Компания / продукт", st.session_state.current_company)
    col2.metric("Этап", st.session_state.current_step)
    col3.metric(
        "Прогресс",
        f"{st.session_state.completed_companies} / {st.session_state.total_companies}",
    )

    with st.expander("Ход процесса", expanded=True):
        if st.session_state.user_updates:
            for item in st.session_state.user_updates[-10:]:
                st.write(item)
        else:
            st.write("Пока нет событий.")

    with st.expander("Технические логи", expanded=False):
        if st.session_state.logs:
            st.caption(f"Показаны последние {min(len(st.session_state.logs), 400)} из {len(st.session_state.logs)} записей.")
            for item in st.session_state.logs[-400:]:
                st.code(item)
        else:
            st.write("Пока нет логов.")


# =========================
# TEXT / JSON HELPERS
# =========================

def clean_text(text: str) -> str:
    if not text:
        return ""

    text = str(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            lines.append(line)

    return "\n".join(lines)


def parse_params_from_text(text: str) -> List[str]:
    if not text:
        return []

    raw_items = []

    for line in text.splitlines():
        line = line.strip()
        line = re.sub(r"^[\-\*\•\d\.\)\s]+", "", line).strip()
        if not line:
            continue

        if ";" in line:
            raw_items.extend([x.strip() for x in line.split(";") if x.strip()])
        elif "," in line and len(line) < 300:
            raw_items.extend([x.strip() for x in line.split(",") if x.strip()])
        else:
            raw_items.append(line)

    seen = set()
    params = []

    for item in raw_items:
        item = item.strip()
        if not item:
            continue

        normalized = item.lower()
        if normalized not in seen:
            seen.add(normalized)
            params.append(item)

    return params


def deduplicate_companies(companies: List[Dict[str, str]]) -> List[Dict[str, str]]:
    result = []
    seen = set()

    for company in companies:
        name = str(company.get("name", "")).strip()
        url = str(company.get("url", "")).strip()
        manual_text = str(company.get("manual_text", "")).strip()

        if not name:
            continue

        if not url and not manual_text:
            continue

        key = (name.lower(), url.lower(), manual_text[:120].lower())
        if key in seen:
            continue

        seen.add(key)
        result.append(
            {
                "name": name,
                "url": url,
                "manual_text": manual_text,
            }
        )

    return result


def ensure_system_params(params: List[str]) -> List[str]:
    result = list(params)

    if "URL источника" not in result:
        result.insert(0, "URL источника")

    if "Что не указано на странице" not in result:
        result.append("Что не указано на странице")

    if "Статус парсинга" not in result:
        result.append("Статус парсинга")

    return result


def extract_json_from_text(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("LLM вернула пустой ответ.")

    cleaned = text.strip()
    cleaned = cleaned.replace("```json", "```")
    cleaned = cleaned.replace("```JSON", "```")

    fenced_match = re.search(r"```(.*?)```", cleaned, flags=re.DOTALL)
    if fenced_match:
        cleaned = fenced_match.group(1).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("JSON должен быть объектом, а не массивом.")
    except json.JSONDecodeError:
        pass

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")

    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        raise ValueError("Не удалось найти JSON-объект в ответе модели.")

    json_fragment = cleaned[first_brace:last_brace + 1]
    parsed = json.loads(json_fragment)

    if not isinstance(parsed, dict):
        raise ValueError("JSON должен быть объектом, а не массивом.")

    return parsed


def normalize_record_to_schema(
    raw_record: Dict[str, Any],
    company_name: str,
    url: str,
    params: List[str],
    parsing_status: str,
) -> Dict[str, Any]:
    record = {"Компания": company_name}

    lower_key_map = {
        str(key).strip().lower(): key
        for key in raw_record.keys()
    }

    for param in params:
        if param == "URL источника":
            record[param] = url if url else "Нет URL / использован ручной текст"
            continue

        if param == "Статус парсинга":
            record[param] = parsing_status
            continue

        key = lower_key_map.get(param.lower())
        value = raw_record.get(key, "Не указано") if key else "Не указано"

        if value is None:
            value = "Не указано"

        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)

        value = str(value).strip()
        if not value:
            value = "Не указано"

        record[param] = value

    return record



def normalize_cell_object(value: Any) -> Dict[str, str]:
    if isinstance(value, dict):
        cell = {"value": value.get("value", "Не указано"), "evidence": value.get("evidence", ""), "source_type": value.get("source_type", "not_found"), "confidence": value.get("confidence", "низкая"), "missing_reason": value.get("missing_reason", "")}
    else:
        text_value = str(value or "Не указано").strip() or "Не указано"
        cell = {"value": text_value, "evidence": "", "source_type": "not_found" if text_value == "Не указано" else "page", "confidence": "низкая" if text_value == "Не указано" else "средняя", "missing_reason": "Данные не найдены в источнике." if text_value == "Не указано" else ""}
    return {key: str(val or "").strip() for key, val in cell.items()}


def normalize_structured_record_to_schema(raw_record: Dict[str, Any], company_name: str, url: str, params: List[str], parsing_status: str) -> Dict[str, Any]:
    record = {"Компания": company_name}
    lower_key_map = {str(key).strip().lower(): key for key in raw_record.keys()}
    for param in params:
        if param == "URL источника":
            record[param] = url if url else "Нет URL / использован ручной текст"
            continue
        if param == "Статус парсинга":
            record[param] = parsing_status
            continue
        key = lower_key_map.get(param.lower())
        cell = normalize_cell_object(raw_record.get(key, "Не указано") if key else "Не указано")
        record[param] = cell["value"] or "Не указано"
        record[f"{param} — Источник значения"] = cell["source_type"] or "not_found"
        record[f"{param} — Фрагмент источника"] = cell["evidence"]
        record[f"{param} — Уверенность"] = cell["confidence"] or "низкая"
        record[f"{param} — Причина отсутствия"] = cell["missing_reason"]
    return record


def parse_numeric_value(value: Any) -> Optional[float]:
    text = str(value or "").lower().replace("\xa0", " ").replace(",", ".")
    if not text or "не указано" in text:
        return None
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    if not numbers:
        return None
    number = float(numbers[0])
    if any(word in text for word in ["млрд", "миллиард"]):
        number *= 1_000_000_000
    elif any(word in text for word in ["млн", "миллион"]):
        number *= 1_000_000
    elif any(word in text for word in ["тыс", "тысяч"]):
        number *= 1_000
    return number


def is_numeric_comparison_param(param: str) -> bool:
    param_l = param.lower()
    return any(token in param_l for token in ["ставк", "пск", "%", "ltv", "сумм", "цен", "стоим", "срок", "комисс", "тариф"])


def add_numeric_normalization_columns(df: pd.DataFrame, params: List[str]) -> pd.DataFrame:
    result = df.copy()
    for param in params:
        if param in result.columns and is_numeric_comparison_param(param):
            result[f"{param} — нормализованное число"] = result[param].apply(parse_numeric_value)
    return result


def merge_record_metadata(final_records: List[Dict[str, Any]], source_records: List[Dict[str, Any]], params: List[str]) -> List[Dict[str, Any]]:
    source_by_company = {str(item.get("Компания", "")).strip().lower(): item for item in source_records}
    for record in final_records:
        source = source_by_company.get(str(record.get("Компания", "")).strip().lower(), {})
        for param in params:
            for suffix in META_COLUMN_SUFFIXES:
                column = f"{param} — {suffix}"
                if column in source and column not in record:
                    record[column] = source[column]
    return final_records


def build_verification_prompt(company_name: str, params: List[str], raw_record: Dict[str, Any], source_text: str) -> str:
    params_json = json.dumps(params, ensure_ascii=False, indent=2)
    record_json = json.dumps(raw_record, ensure_ascii=False, indent=2)
    return f"""
Проверь извлеченные значения по исходному тексту.

Компания:
{company_name}

Параметры:
{params_json}

Текущая запись:
{record_json}

Верни только валидный JSON-объект такого вида:
{{
  "updates": {{
    "Название параметра": {{
      "value": "...", "evidence": "...", "source_type": "page | document | manual_text | parser_metadata | not_found", "confidence": "высокая | средняя | низкая", "missing_reason": "..."
    }}
  }},
  "notes": "кратко, что было исправлено"
}}

Проверяй только спорные значения: низкая уверенность, пустой evidence, числовые поля, ставки, суммы, сроки, комиссии, тарифы.
Не выдумывай факты и не добавляй знания вне текста.

Исходный текст:
{source_text[:MAX_SOURCE_CHARS]}
""".strip()


def verify_record_with_llm(company_name: str, params: List[str], raw_record: Dict[str, Any], source_text: str, enabled: bool) -> Dict[str, Any]:
    if not enabled:
        return raw_record
    needs_check = False
    for param in params:
        cell = normalize_cell_object(raw_record.get(param, "Не указано"))
        if cell["confidence"].lower() in LOW_CONFIDENCE_VALUES or (cell["value"] != "Не указано" and not cell["evidence"]) or is_numeric_comparison_param(param):
            needs_check = True
    if not needs_check:
        return raw_record
    try:
        prompt = build_verification_prompt(company_name, params, raw_record, source_text)
        response_text = call_llm(prompt)
        parsed = extract_json_from_text(response_text)
        updates = parsed.get("updates", {})
        if isinstance(updates, dict):
            for key, value in updates.items():
                if key in params:
                    raw_record[key] = value
            log(f"{company_name}: повторная проверка спорных значений выполнена.")
    except Exception as exc:
        log(f"{company_name}: повторная проверка не выполнена: {repr(exc)}")
    return raw_record


def build_comparison_insights(df: pd.DataFrame, params: List[str]) -> List[str]:
    insights = []
    for param in params:
        normalized_col = f"{param} — нормализованное число"
        if param not in df.columns or normalized_col not in df.columns:
            continue
        numeric = pd.to_numeric(df[normalized_col], errors="coerce")
        if numeric.notna().sum() < 2:
            continue
        param_l = param.lower()
        lower_is_better = any(token in param_l for token in ["ставк", "пск", "цен", "стоим", "комисс", "срок"])
        best_index = numeric.idxmin() if lower_is_better else numeric.idxmax()
        insights.append(f"{param}: лучшее значение у {df.loc[best_index, 'Компания']} — {df.loc[best_index, param]}")
    return insights


def highlight_best_values(df: pd.DataFrame) -> pd.DataFrame:
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    for numeric_col in [col for col in df.columns if col.endswith("— нормализованное число")]:
        base_col = numeric_col.replace(" — нормализованное число", "")
        if base_col not in df.columns:
            continue
        numeric = pd.to_numeric(df[numeric_col], errors="coerce")
        if numeric.notna().sum() < 2:
            continue
        base_l = base_col.lower()
        lower_is_better = any(token in base_l for token in ["ставк", "пск", "цен", "стоим", "комисс", "срок"])
        best_index = numeric.idxmin() if lower_is_better else numeric.idxmax()
        styles.loc[best_index, base_col] = "background-color: #d9ead3"
    return styles


def visible_result_columns(df: pd.DataFrame) -> List[str]:
    return [column for column in df.columns if not column.endswith("— нормализованное число")]


def render_result_section(df: pd.DataFrame, params: List[str], editor_key: str) -> pd.DataFrame:
    insights = build_comparison_insights(df, params)
    st.session_state.last_comparison_insights = insights
    if insights:
        with st.expander("Автоматические выводы и лучшие значения", expanded=True):
            for insight in insights:
                st.write(f"• {insight}")
    with st.expander("Редактор результата перед скачиванием", expanded=True):
        editable_columns = visible_result_columns(df)
        edited_df = st.data_editor(df[editable_columns], use_container_width=True, num_rows="fixed", key=editor_key)
    st.dataframe(df.style.apply(highlight_best_values, axis=None), use_container_width=True)
    result_df = df.copy()
    for column in editable_columns:
        result_df[column] = edited_df[column]
    return result_df


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Battle Card")
        worksheet = writer.sheets["Battle Card"]

        for column_cells in worksheet.columns:
            max_length = 0
            column_letter = column_cells[0].column_letter

            for cell in column_cells:
                value = cell.value
                if value is None:
                    continue
                max_length = max(max_length, len(str(value)))

            adjusted_width = min(max_length + 2, 60)
            worksheet.column_dimensions[column_letter].width = adjusted_width

        for row in worksheet.iter_rows():
            for cell in row:
                cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")

    output.seek(0)
    return output.getvalue()


# =========================
# DOCUMENT HELPERS
# =========================

FILE_EXTENSIONS = [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv"]

RELEVANT_DOC_KEYWORDS = [
    "услов", "тариф", "правил", "документ", "памят", "договор",
    "пск", "полная стоимость", "страхован", "требован", "анкета",
    "залог", "кредит", "ипотек", "раскрытие", "регламент",
    "комис", "ставк", "заемщик", "заёмщик", "оферт", "положение",
    "каско", "осаго", "страховая сумма", "франшиза", "gap"
]


def normalize_link(href: str, base_url: str) -> str:
    if not href:
        return ""

    href = href.strip()

    if href.startswith("//"):
        return "https:" + href

    return urljoin(base_url, href)


def is_relevant_document_link(href: str, text: str = "") -> bool:
    href_l = (href or "").lower()
    has_file_ext = any(ext in href_l for ext in FILE_EXTENSIONS)

    return has_file_ext


def download_binary(url: str, timeout: int = 35) -> bytes:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }

    response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response.content


def extract_text_from_pdf_bytes(content: bytes) -> str:
    output = []

    reader = PdfReader(io.BytesIO(content))

    for i, page in enumerate(reader.pages[:MAX_PDF_PAGES], start=1):
        try:
            text = page.extract_text() or ""
            text = clean_text(text)
            if text:
                output.append(f"\n--- PDF, страница {i} ---\n{text}")
        except Exception:
            continue

    return clean_text("\n".join(output))


def extract_text_from_docx_bytes(content: bytes) -> str:
    document = docx.Document(io.BytesIO(content))
    parts = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            parts.append(text)

    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            cells = [cell for cell in cells if cell]
            if cells:
                parts.append(" | ".join(cells))

    return clean_text("\n".join(parts))


def extract_text_from_xlsx_bytes(content: bytes) -> str:
    xls = pd.ExcelFile(io.BytesIO(content))
    parts = []

    for sheet in xls.sheet_names[:10]:
        try:
            df = pd.read_excel(xls, sheet_name=sheet, dtype=str)
            df = df.fillna("")
            text = df.to_csv(index=False, sep=";")
            parts.append(f"\n--- XLSX/XLS, лист: {sheet} ---\n{text}")
        except Exception:
            continue

    return clean_text("\n".join(parts))


def extract_text_from_downloaded_file(url: str, content: bytes) -> str:
    url_l = url.lower()

    if ".pdf" in url_l:
        return extract_text_from_pdf_bytes(content)

    if ".docx" in url_l:
        return extract_text_from_docx_bytes(content)

    if ".xlsx" in url_l or ".xls" in url_l:
        return extract_text_from_xlsx_bytes(content)

    if ".csv" in url_l:
        return clean_text(content.decode("utf-8", errors="ignore"))

    return ""


def fetch_relevant_documents_texts(document_links: List[str], max_files: int = MAX_DOCUMENT_FILES) -> str:
    parts = []
    processed = 0
    total_links = len(document_links)

    log(f"Документы: найдено релевантных ссылок: {total_links}; лимит обработки файлов: {max_files}")

    for index, item in enumerate(document_links, start=1):
        if processed >= max_files:
            log(f"Документы: достигнут лимит {max_files}, остальные ссылки пропущены.")
            break

        if ": http" in item:
            label, url = item.rsplit(": ", 1)
        else:
            label, url = "", item

        try:
            log(f"Документы: [{index}/{total_links}] скачиваю: {url}")
            if label:
                log(f"Документы: подпись ссылки: {shorten_log_text(label)}")
            content = download_binary(url)
            log(f"Документы: [{index}/{total_links}] скачано байт: {len(content)}")
            text = extract_text_from_downloaded_file(url, content)
            log(f"Документы: [{index}/{total_links}] извлечено символов текста: {len(text)}")

            if text and len(text) >= 100:
                processed += 1
                parts.append(
                    f"\n=== ТЕКСТ ИЗ ДОКУМЕНТА ===\n"
                    f"Название ссылки: {label or 'Не указано'}\n"
                    f"URL документа: {url}\n\n"
                    f"{text[:MAX_DOCUMENT_CHARS]}"
                )
                log(f"Документы: обработан файл {processed}/{max_files}: {url}")
            else:
                parts.append(
                    f"\n=== ДОКУМЕНТ НАЙДЕН, НО ТЕКСТ НЕ ИЗВЛЕЧЁН ===\n"
                    f"Название ссылки: {label or 'Не указано'}\n"
                    f"URL документа: {url}"
                )
                log(f"Документы: текст не извлечён или слишком короткий: {url}")

        except Exception as exc:
            log(f"Ошибка скачивания/чтения документа {url}: {repr(exc)}")
            parts.append(
                f"\n=== ДОКУМЕНТ НАЙДЕН, НО НЕ ОБРАБОТАН ===\n"
                f"URL документа: {url}\n"
                f"Ошибка: {repr(exc)}"
            )

    log(f"Документы: итогово успешно обработано файлов: {processed}; блоков в выдаче: {len(parts)}")
    return clean_text("\n".join(parts))


# =========================
# PARSERS
# =========================

def fetch_text_requests(url: str) -> str:
    log(f"requests: старт загрузки HTML: {url}")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Connection": "keep-alive",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=REQUESTS_TIMEOUT,
        allow_redirects=True,
    )

    log(
        "requests: ответ получен: "
        f"status={response.status_code}, final_url={response.url}, bytes={len(response.content)}"
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    removed_tags = 0
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
        removed_tags += 1

    text = soup.get_text("\n")
    cleaned_text = clean_text(text)
    log(f"requests: HTML очищен; удалено служебных тегов: {removed_tags}; символов текста: {len(cleaned_text)}")
    return cleaned_text


def force_expand_bootstrap_blocks(page) -> int:
    try:
        return page.evaluate("""
        () => {
            let count = 0;

            document.querySelectorAll('.accordion-collapse, .collapse, .tab-pane').forEach(el => {
                el.classList.add('show');
                el.classList.add('active');
                el.style.display = 'block';
                el.style.visibility = 'visible';
                el.style.height = 'auto';
                el.style.maxHeight = 'none';
                el.style.opacity = '1';
                el.removeAttribute('hidden');
                count += 1;
            });

            document.querySelectorAll('[aria-expanded="false"]').forEach(el => {
                el.setAttribute('aria-expanded', 'true');
            });

            document.querySelectorAll('[hidden]').forEach(el => {
                el.removeAttribute('hidden');
                el.style.display = 'block';
                el.style.visibility = 'visible';
            });

            return count;
        }
        """)
    except Exception:
        return 0


def collect_bootstrap_accordion_text(page) -> str:
    try:
        items = page.evaluate("""
        () => {
            const result = [];

            document.querySelectorAll('.accordion-item, .faq__question').forEach((item, index) => {
                const questionEl =
                    item.querySelector('.accordion-button') ||
                    item.querySelector('.accordion-header') ||
                    item.querySelector('button') ||
                    item.querySelector('[role="button"]');

                const answerEl =
                    item.querySelector('.accordion-body') ||
                    item.querySelector('.inner-text') ||
                    item.querySelector('.accordion-collapse') ||
                    item.querySelector('.collapse');

                const question = questionEl ? questionEl.textContent.trim() : '';
                const answer = answerEl ? answerEl.textContent.trim() : '';

                if (question || answer) {
                    result.push({
                        index: index + 1,
                        question,
                        answer
                    });
                }
            });

            return result;
        }
        """)

        parts = []

        for item in items:
            question = clean_text(item.get("question", ""))
            answer = clean_text(item.get("answer", ""))

            if question or answer:
                parts.append(f"Вопрос: {question}\nОтвет: {answer}")

        return clean_text("\n\n".join(parts))

    except Exception:
        return ""


def collect_hidden_dom_text(page) -> str:
    try:
        return page.evaluate("""
        () => {
            const parts = [];

            document.querySelectorAll(
                '.collapse, .accordion-body, .accordion-collapse, .tab-pane, [hidden], .faq__question, .inner-text'
            ).forEach(el => {
                const txt = el.textContent;
                if (txt && txt.trim().length > 50) {
                    parts.push(txt.trim());
                }
            });

            return parts.join('\\n\\n');
        }
        """)
    except Exception:
        return ""


def collect_visible_body_text(page) -> str:
    texts = []

    try:
        body_text = page.locator("body").inner_text(timeout=15000)
        if body_text:
            texts.append(body_text)
    except Exception:
        pass

    try:
        accordion_text = collect_bootstrap_accordion_text(page)
        if accordion_text:
            texts.append("\n=== ТЕКСТ ИЗ BOOTSTRAP-АККОРДЕОНОВ / FAQ ===\n" + accordion_text)
    except Exception:
        pass

    try:
        hidden_text = collect_hidden_dom_text(page)
        if hidden_text:
            texts.append("\n=== ТЕКСТ ИЗ СКРЫТЫХ DOM-БЛОКОВ ===\n" + hidden_text)
    except Exception:
        pass

    return clean_text("\n\n".join(texts))


def click_cookie_banners(page) -> int:
    clicked = 0

    selectors = [
        "button:has-text('Принять')",
        "button:has-text('Согласен')",
        "button:has-text('Согласна')",
        "button:has-text('Соглашаюсь')",
        "button:has-text('Хорошо')",
        "button:has-text('Понятно')",
        "button:has-text('Ок')",
        "button:has-text('OK')",
        "button:has-text('Закрыть')",
        "button:has-text('Не сейчас')",
        "[aria-label='Close']",
        "[aria-label='Закрыть']",
        "[data-testid='close']",
    ]

    for selector in selectors:
        try:
            elements = page.locator(selector)
            count = min(elements.count(), 5)

            for i in range(count):
                try:
                    element = elements.nth(i)
                    if element.is_visible(timeout=800):
                        element.click(timeout=2000)
                        clicked += 1
                        page.wait_for_timeout(400)
                except Exception:
                    pass
        except Exception:
            pass

    return clicked


def scroll_page_deeply(page, max_rounds: int = 8, log_prefix: str = "") -> None:
    last_height = 0
    prefix = f"{log_prefix}: " if log_prefix else ""

    log(f"{prefix}скроллинг страницы: старт, максимум раундов: {max_rounds}")

    for round_index in range(1, max_rounds + 1):
        try:
            current_height = page.evaluate("document.body.scrollHeight")
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(800)

            new_height = page.evaluate("document.body.scrollHeight")
            log(
                f"{prefix}скроллинг раунд {round_index}/{max_rounds}: "
                f"высота до={current_height}, после={new_height}"
            )

            if new_height == last_height and current_height == last_height:
                log(f"{prefix}скроллинг остановлен: высота страницы больше не меняется.")
                break

            last_height = new_height
        except Exception as exc:
            log(f"{prefix}скроллинг остановлен из-за ошибки: {repr(exc)}")
            break

    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)
        log(f"{prefix}скроллинг завершён, страница возвращена наверх.")
    except Exception:
        log(f"{prefix}не удалось вернуть страницу наверх после скроллинга.")
        pass


def get_element_label(element) -> str:
    parts = []

    try:
        inner_text = element.inner_text(timeout=700)
        if inner_text:
            parts.append(inner_text)
    except Exception:
        pass

    for attr in ["aria-label", "title", "data-testid", "data-qa", "data-qa-type", "class"]:
        try:
            value = element.get_attribute(attr)
            if value:
                parts.append(value)
        except Exception:
            pass

    label = " ".join(parts)
    label = clean_text(label)
    return label[:260]


def is_safe_expand_text(text: str) -> bool:
    if not text:
        return False

    t = text.strip().lower()
    t = re.sub(r"\s+", " ", t)

    if len(t) > 280:
        return False

    unsafe_patterns = [
        "оформить",
        "купить",
        "оплатить",
        "заказать",
        "оставить заявку",
        "подать заявку",
        "получить карту",
        "получить кредит",
        "войти",
        "личный кабинет",
        "зарегистрироваться",
        "продолжить",
        "перейти к оплате",
        "отправить",
        "позвонить",
        "оставьте телефон",
        "оставить телефон",
        "заполнить",
        "скачать приложение",
        "открыть счет",
        "открыть счёт",
    ]

    if any(pattern in t for pattern in unsafe_patterns):
        return False

    safe_patterns = [
        "показать",
        "раскрыть",
        "развернуть",
        "подробнее",
        "читать далее",
        "ещё",
        "еще",
        "услов",
        "тариф",
        "документ",
        "требован",
        "вопрос",
        "ответ",
        "faq",
        "как оформить",
        "что входит",
        "исключения",
        "ограничения",
        "преимущества",
        "детали",
        "смотреть",
        "раздел",
        "правила",
        "о продукте",
        "пск",
        "ставки",
        "комис",
        "страх",
        "франшиза",
        "gap",
        "тотал",
    ]

    return any(pattern in t for pattern in safe_patterns)


def strip_url_fragment(url: str) -> str:
    return str(url or "").split("#", 1)[0]


def get_element_navigation_metadata(element) -> Dict[str, str]:
    try:
        metadata = element.evaluate("""
        el => ({
            tag: (el.tagName || '').toLowerCase(),
            href: el.getAttribute('href') || '',
            target: el.getAttribute('target') || '',
            role: el.getAttribute('role') || '',
            ariaControls: el.getAttribute('aria-controls') || '',
            ariaExpanded: el.getAttribute('aria-expanded') || '',
            dataBsToggle: el.getAttribute('data-bs-toggle') || '',
            dataToggle: el.getAttribute('data-toggle') || '',
            dataQaType: el.getAttribute('data-qa-type') || '',
            dataQa: el.getAttribute('data-qa') || '',
            className: String(el.className || '')
        })
        """)

        return {
            str(key): str(value or "")
            for key, value in metadata.items()
        }
    except Exception:
        return {}


def is_same_page_toggle_candidate(metadata: Dict[str, str], current_url: str) -> bool:
    tag = metadata.get("tag", "").lower()
    href = metadata.get("href", "").strip()
    href_l = href.lower()
    combined = " ".join(
        [
            metadata.get("role", ""),
            metadata.get("ariaControls", ""),
            metadata.get("ariaExpanded", ""),
            metadata.get("dataBsToggle", ""),
            metadata.get("dataToggle", ""),
            metadata.get("dataQaType", ""),
            metadata.get("dataQa", ""),
            metadata.get("className", ""),
        ]
    ).lower()

    toggle_markers = [
        "accordion",
        "collapse",
        "tab",
        "tabs",
        "spoiler",
        "faq",
        "dropdown",
    ]

    if tag == "summary":
        return True

    has_toggle_marker = any(marker in combined for marker in toggle_markers)
    has_aria_toggle = bool(metadata.get("ariaControls") or metadata.get("ariaExpanded"))
    has_button_role = metadata.get("role", "").lower() in {"button", "tab"}

    if tag == "a":
        if metadata.get("target", "").lower() == "_blank":
            return False

        if not href or href_l in {"#", "javascript:void(0)", "javascript:void(0);"}:
            return has_toggle_marker or has_aria_toggle or has_button_role or href_l.startswith("javascript")

        if href_l.startswith("javascript:"):
            return has_toggle_marker or has_aria_toggle or has_button_role

        normalized_href = normalize_link(href, current_url)
        if href.startswith("#") or (
            "#" in normalized_href
            and strip_url_fragment(normalized_href) == strip_url_fragment(current_url)
        ):
            return True

        return False

    return has_toggle_marker or has_aria_toggle or has_button_role or tag == "button"


def close_extra_pages_after_click(page, before_pages_count: int, log_prefix: str = "") -> None:
    prefix = f"{log_prefix}: " if log_prefix else ""

    try:
        pages = page.context.pages
        if len(pages) <= before_pages_count:
            return

        extra_pages = pages[before_pages_count:]
        log(f"{prefix}клик открыл новых вкладок/страниц: {len(extra_pages)}; закрываю их.")
        for extra_page in extra_pages:
            try:
                extra_page.close()
            except Exception:
                pass
    except Exception:
        pass


def recover_current_page_after_navigation(page, before_url: str, log_prefix: str = "") -> bool:
    prefix = f"{log_prefix}: " if log_prefix else ""

    try:
        after_url = page.url
    except Exception:
        return False

    if strip_url_fragment(after_url) == strip_url_fragment(before_url):
        return False

    log(
        f"{prefix}клик вызвал переход вне текущей страницы; "
        f"возвращаюсь назад. Было: {before_url}; стало: {after_url}"
    )

    try:
        page.go_back(wait_until="domcontentloaded", timeout=8000)
        page.wait_for_timeout(800)
        return True
    except Exception as exc:
        log(f"{prefix}go_back не сработал после нежелательного перехода: {repr(exc)}")

    try:
        page.goto(before_url, wait_until="domcontentloaded", timeout=12000)
        page.wait_for_timeout(800)
        return True
    except Exception as exc:
        log(f"{prefix}не удалось восстановить исходную страницу: {repr(exc)}")
        return True


def click_safe_expandable_elements(page, max_clicks: int = 150, log_prefix: str = "") -> List[str]:
    clicked_labels = []
    clicked_fingerprints = set()
    skipped_navigation_count = 0
    prefix = f"{log_prefix}: " if log_prefix else ""

    selectors = [
        "summary",
        "[aria-expanded='false'][aria-controls]",
        "[aria-controls][role='button']",
        "[aria-controls][role='tab']",
        "[role='tab']",
        "[data-bs-toggle='collapse']",
        "[data-bs-toggle='tab']",
        "[data-toggle='collapse']",
        "[data-toggle='tab']",
        "a[href^='#'][data-bs-toggle]",
        "a[href^='#'][data-toggle]",
        "a[href^='#'][role='tab']",
        ".accordion-button",
        ".accordion-header button",
        ".faq__question",
        "[data-testid*='accordion']",
        "[data-testid*='collapse']",
        "[data-testid*='faq']",
        "[data-testid*='tab']",
        "[data-qa-type='uikit/accordion.item']",
        "[data-qa-type*='accordion']",
        "[data-qa-type*='Accordion']",
        "[data-qa-type*='collapse']",
        "[data-qa-type*='Collapse']",
        "[data-qa-type*='spoiler']",
        "[data-qa-type*='tab']",
        "[data-qa-type*='Tab']",
        "[data-qa*='accordion']",
        "[data-qa*='collapse']",
        "[data-qa*='tab']",
        "[class*='accordion'] button",
        "[class*='Accordion'] button",
        "[class*='faq'] button",
        "[class*='Faq'] button",
        "[class*='spoiler'] button",
        "[class*='Spoiler'] button",
        "[class*='collapse'] button",
        "[class*='Collapse'] button",
        "[class*='tabs'] button",
        "[class*='Tabs'] button",
    ]

    log(f"{prefix}поиск раскрываемых элементов: старт, селекторов: {len(selectors)}, лимит кликов: {max_clicks}")

    for selector in selectors:
        try:
            elements = page.locator(selector)
            count = min(elements.count(), 120)
            if count:
                log(f"{prefix}селектор раскрытия '{selector}': найдено элементов: {count}")

            for i in range(count):
                if len(clicked_labels) >= max_clicks:
                    log(f"{prefix}достигнут лимит кликов раскрытия: {max_clicks}")
                    return clicked_labels

                try:
                    element = elements.nth(i)

                    try:
                        if not element.is_visible(timeout=700):
                            continue
                    except Exception:
                        continue

                    combined_label = get_element_label(element)

                    if not combined_label:
                        continue

                    if not is_safe_expand_text(combined_label):
                        continue

                    metadata = get_element_navigation_metadata(element)
                    current_url = page.url

                    if not is_same_page_toggle_candidate(metadata, current_url):
                        skipped_navigation_count += 1
                        if skipped_navigation_count <= 30 or skipped_navigation_count % 50 == 0:
                            href = metadata.get("href", "")
                            log(
                                f"{prefix}пропущен элемент с риском перехода: "
                                f"{shorten_log_text(combined_label)}"
                                f"{' | href=' + shorten_log_text(href, 120) if href else ''}"
                            )
                        continue

                    fingerprint = f"{selector}|{i}|{combined_label.lower()[:160]}"
                    if fingerprint in clicked_fingerprints:
                        continue

                    clicked_fingerprints.add(fingerprint)

                    try:
                        element.scroll_into_view_if_needed(timeout=2000)
                        page.wait_for_timeout(250)
                    except Exception:
                        pass

                    before_url = page.url
                    before_pages_count = 0
                    try:
                        before_pages_count = len(page.context.pages)
                    except Exception:
                        pass

                    try:
                        element.click(timeout=2500, force=False)
                    except Exception:
                        try:
                            element.click(timeout=2500, force=True)
                        except Exception:
                            continue

                    page.wait_for_timeout(250)
                    close_extra_pages_after_click(
                        page,
                        before_pages_count=before_pages_count,
                        log_prefix=log_prefix,
                    )
                    navigated_away = recover_current_page_after_navigation(
                        page,
                        before_url=before_url,
                        log_prefix=log_prefix,
                    )

                    if navigated_away:
                        continue

                    clicked_labels.append(combined_label[:220])
                    if len(clicked_labels) <= 25 or len(clicked_labels) % 10 == 0:
                        log(
                            f"{prefix}раскрыт элемент #{len(clicked_labels)} "
                            f"через '{selector}': {shorten_log_text(combined_label)}"
                        )
                    page.wait_for_timeout(450)

                except Exception:
                    continue

        except Exception:
            continue

    log(
        f"{prefix}поиск раскрываемых элементов завершён; "
        f"кликов выполнено: {len(clicked_labels)}, "
        f"пропущено из-за риска перехода: {skipped_navigation_count}"
    )
    return clicked_labels


def extract_document_links(page, base_url: str) -> List[str]:
    links = []
    skipped_keyword_only_links = 0

    try:
        anchors = page.locator("a")
        count = min(anchors.count(), 1500)

        for i in range(count):
            try:
                anchor = anchors.nth(i)
                href = anchor.get_attribute("href") or ""

                try:
                    text = anchor.inner_text(timeout=500)
                except Exception:
                    text = ""

                href = normalize_link(href, base_url)

                if not href.startswith("http"):
                    continue

                if not is_relevant_document_link(href, text):
                    combined = f"{href} {text}".lower()
                    if any(word in combined for word in RELEVANT_DOC_KEYWORDS):
                        skipped_keyword_only_links += 1
                    continue

                label = clean_text(text)
                item = f"{label}: {href}" if label else href

                if item not in links:
                    links.append(item)

            except Exception:
                continue

    except Exception:
        pass

    if skipped_keyword_only_links:
        log(
            "Документы: пропущено ссылок на HTML-страницы без прямого файла "
            f"(чтобы не уходить с текущей страницы): {skipped_keyword_only_links}"
        )

    return links


def fetch_text_playwright(url: str, company_name: str = "") -> str:
    log_prefix = company_name or "Playwright"

    try:
        with sync_playwright() as p:
            log(f"{log_prefix}: Playwright стартовал, запускаю Chromium.")
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-setuid-sandbox",
                ],
            )
            log(f"{log_prefix}: Chromium запущен в headless-режиме.")

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="ru-RU",
                viewport={"width": 1440, "height": 1800},
                java_script_enabled=True,
                accept_downloads=True,
            )
            log(f"{log_prefix}: создан browser context: locale=ru-RU, viewport=1440x1800.")

            page = context.new_page()
            log(f"{log_prefix}: открываю страницу: {url}")

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=PLAYWRIGHT_TIMEOUT,
            )
            log(f"{log_prefix}: domcontentloaded получен.")

            try:
                page.wait_for_load_state("networkidle", timeout=5000)
                log(f"{log_prefix}: networkidle получен.")
            except Exception as exc:
                log(f"{log_prefix}: networkidle не дождались за 5 секунд: {repr(exc)}")
                pass

            page.wait_for_timeout(2000)
            try:
                log(f"{log_prefix}: текущий URL после редиректов: {page.url}")
                log(f"{log_prefix}: title страницы: {shorten_log_text(page.title(), 180)}")
            except Exception as exc:
                log(f"{log_prefix}: не удалось прочитать URL/title: {repr(exc)}")

            cookies_clicked = click_cookie_banners(page)
            log(f"{log_prefix}: cookie/pop-up кнопок закрыто: {cookies_clicked}")

            expanded_bootstrap_count_1 = force_expand_bootstrap_blocks(page)
            log(f"{log_prefix}: Bootstrap/collapse блоков раскрыто через DOM, раунд 1: {expanded_bootstrap_count_1}")

            scroll_page_deeply(page, max_rounds=5, log_prefix=f"{log_prefix}: первичный проход")
            initial_text = collect_visible_body_text(page)
            log(f"{log_prefix}: текст после первичного прохода: {len(initial_text)} символов.")

            clicked_labels_round_1 = click_safe_expandable_elements(
                page,
                max_clicks=45,
                log_prefix=f"{log_prefix}: раскрытие раунд 1",
            )
            log(f"{log_prefix}: кликов раскрытия в раунде 1: {len(clicked_labels_round_1)}")
            expanded_bootstrap_count_2 = force_expand_bootstrap_blocks(page)
            log(f"{log_prefix}: Bootstrap/collapse блоков раскрыто через DOM, раунд 2: {expanded_bootstrap_count_2}")

            scroll_page_deeply(page, max_rounds=3, log_prefix=f"{log_prefix}: второй проход")
            clicked_labels_round_2 = click_safe_expandable_elements(
                page,
                max_clicks=30,
                log_prefix=f"{log_prefix}: раскрытие раунд 2",
            )
            log(f"{log_prefix}: кликов раскрытия в раунде 2: {len(clicked_labels_round_2)}")
            expanded_bootstrap_count_3 = force_expand_bootstrap_blocks(page)
            log(f"{log_prefix}: Bootstrap/collapse блоков раскрыто через DOM, раунд 3: {expanded_bootstrap_count_3}")

            scroll_page_deeply(page, max_rounds=2, log_prefix=f"{log_prefix}: третий проход")
            clicked_labels_round_3 = click_safe_expandable_elements(
                page,
                max_clicks=20,
                log_prefix=f"{log_prefix}: раскрытие раунд 3",
            )
            log(f"{log_prefix}: кликов раскрытия в раунде 3: {len(clicked_labels_round_3)}")
            expanded_bootstrap_count_4 = force_expand_bootstrap_blocks(page)
            log(f"{log_prefix}: Bootstrap/collapse блоков раскрыто через DOM, раунд 4: {expanded_bootstrap_count_4}")

            final_text = collect_visible_body_text(page)
            log(f"{log_prefix}: финальный текст страницы после раскрытий: {len(final_text)} символов.")
            document_links = extract_document_links(page, url)
            log(f"{log_prefix}: найдено ссылок на документы / условия: {len(document_links)}")
            for doc_index, doc_link in enumerate(document_links[:10], start=1):
                log(f"{log_prefix}: документ #{doc_index}: {shorten_log_text(doc_link, 260)}")
            if len(document_links) > 10:
                log(f"{log_prefix}: ещё документов сверх первых 10: {len(document_links) - 10}")

            context.close()
            browser.close()
            log(f"{log_prefix}: browser context и Chromium закрыты.")

            log(f"{log_prefix}: начинаю обработку найденных документов.")
            documents_text = fetch_relevant_documents_texts(
                document_links=document_links,
                max_files=MAX_DOCUMENT_FILES,
            )
            log(f"{log_prefix}: текст из документов: {len(documents_text)} символов.")

            clicked_labels = clicked_labels_round_1 + clicked_labels_round_2 + clicked_labels_round_3
            expanded_total = (
                expanded_bootstrap_count_1
                + expanded_bootstrap_count_2
                + expanded_bootstrap_count_3
                + expanded_bootstrap_count_4
            )

            parts = []
            parts.append("=== МЕТАДАННЫЕ ПАРСИНГА ===")
            parts.append(f"URL: {url}")
            parts.append(f"Cookie/pop-up закрыто: {cookies_clicked}")
            parts.append(f"Раскрытых элементов кликом: {len(clicked_labels)}")
            parts.append(f"Bootstrap/collapse/tab блоков раскрыто через DOM: {expanded_total}")
            parts.append(f"Найденных ссылок на документы / условия: {len(document_links)}")

            if initial_text:
                parts.append("\n=== ТЕКСТ ДО ДОПОЛНИТЕЛЬНЫХ КЛИКОВ ===")
                parts.append(initial_text)

            if clicked_labels:
                parts.append("\n=== РАСКРЫТЫЕ ЭЛЕМЕНТЫ КЛИКОМ ===")
                for label in clicked_labels:
                    parts.append(f"- {label}")

            if final_text:
                parts.append("\n=== ТЕКСТ ПОСЛЕ РАСКРЫТИЯ БЛОКОВ ===")
                parts.append(final_text)

            if document_links:
                parts.append("\n=== НАЙДЕННЫЕ ССЫЛКИ НА ДОКУМЕНТЫ / УСЛОВИЯ ===")
                for link in document_links:
                    parts.append(link)

            if documents_text:
                parts.append("\n=== ИЗВЛЕЧЁННЫЙ ТЕКСТ ИЗ ДОКУМЕНТОВ / ТАРИФОВ / УСЛОВИЙ ===")
                parts.append(documents_text)

            combined_text = "\n".join(parts)
            cleaned_combined_text = clean_text(combined_text)
            log(
                f"{log_prefix}: итоговый deep source собран: "
                f"{len(cleaned_combined_text)} символов, кликов={len(clicked_labels)}, "
                f"DOM-раскрытий={expanded_total}, документов={len(document_links)}"
            )
            return cleaned_combined_text

    except Exception as exc:
        log(f"{log_prefix}: критическая ошибка Playwright-парсинга: {repr(exc)}")
        error_text = str(exc)

        if "Executable doesn't exist" in error_text or "playwright install" in error_text:
            raise RuntimeError(
                "Playwright установлен, но браузер Chromium не скачан. "
                "В Render нужно добавить Environment Variable: PLAYWRIGHT_BROWSERS_PATH=0, "
                "а в build command добавить: python -m playwright install chromium. "
                "После этого выполнить Manual Deploy → Clear build cache & deploy."
            ) from exc

        raise


def get_page_text(
    url: str,
    company_name: str,
    live_ui: Optional[Dict[str, Any]] = None,
    started_at: Optional[float] = None,
) -> Dict[str, Any]:
    result = {
        "text": "",
        "method": "",
        "status": "Ошибка парсинга",
        "error": "",
    }

    # ВАЖНО: расширенный парсинг запускается на любом сайте и в любом режиме.
    # requests используется только как дополнительный быстрый источник,
    # но итоговый source_text строится преимущественно через Playwright deep parser.
    quick_text = ""

    try:
        log(f"{company_name}: пробую requests как дополнительный источник: {url}")
        quick_text = fetch_text_requests(url)
        log(f"{company_name}: requests получил символов: {len(quick_text)}")
    except Exception as exc:
        log(f"{company_name}: requests ошибка: {repr(exc)}")

    try:
        log(f"{company_name}: запускаю обязательный расширенный Playwright-парсинг: {url}")

        if live_ui and started_at:
            render_live_status(
                ui=live_ui,
                status=f"Анализ: {company_name}",
                step="Расширенный парсинг страницы",
                company=company_name,
                progress=st.session_state.progress_value,
                completed=st.session_state.completed_companies,
                total=st.session_state.total_companies,
                started_at=started_at,
                last_event=f"{company_name}: запускаю deep parsing: страница, аккордеоны, табы, скрытые блоки, документы.",
            )

        deep_text = fetch_text_playwright(url, company_name=company_name)

        parts = []
        parts.append("=== DEEP PLAYWRIGHT SOURCE ===")
        parts.append(deep_text)

        if quick_text and len(quick_text) >= 500:
            parts.append("\n=== REQUESTS SOURCE, ДОПОЛНИТЕЛЬНО ===")
            parts.append(quick_text)

        combined_text = clean_text("\n\n".join(parts))

        if len(combined_text) >= 300:
            result["text"] = combined_text
            result["method"] = "playwright_deep_required"
            result["status"] = "ОК"
            log(f"{company_name}: обязательный расширенный парсинг успешно, символов: {len(combined_text)}")
            return result

        result["text"] = combined_text
        result["method"] = "playwright_deep_required"
        result["status"] = "Мало текста"
        result["error"] = f"Получено мало текста: {len(combined_text)} символов."
        log(f"{company_name}: расширенный парсинг вернул мало текста: {len(combined_text)} символов")
        return result

    except Exception as exc:
        result["error"] = traceback.format_exc()
        log(f"{company_name}: Playwright ошибка: {repr(exc)}")

        if quick_text and len(quick_text) >= 300:
            result["text"] = quick_text
            result["method"] = "requests_fallback_after_playwright_error"
            result["status"] = "Частично: Playwright не сработал, использован requests"
            return result

        return result


# =========================
# LLM LOGIC
# =========================

def get_llm_client():
    if not YANDEX_FOLDER or not YANDEX_API_KEY:
        return None

    return openai.OpenAI(
        api_key=YANDEX_API_KEY,
        base_url=YANDEX_BASE_URL,
        project=YANDEX_FOLDER,
    )


client = get_llm_client()


def call_llm(prompt: str) -> str:
    if client is None:
        raise RuntimeError(
            "Не заданы переменные окружения YANDEX_FOLDER и/или YANDEX_API_KEY. "
            "Укажите их в Render Environment Variables или локально."
        )

    response = client.responses.create(
        model=f"gpt://{YANDEX_FOLDER}/{YANDEX_MODEL}",
        input=prompt,
        temperature=0.1,
    )

    if hasattr(response, "output_text"):
        return response.output_text

    return str(response)


def build_extraction_prompt(
    battle_card_name: str,
    product_name: str,
    company_name: str,
    url: str,
    source_text: str,
    params: List[str],
) -> str:
    params_json = json.dumps(params, ensure_ascii=False, indent=2)

    return f"""
Ты аналитик, который заполняет battle card / сравнительную таблицу по данным с сайта, скрытых блоков, документов или ручного текста пользователя.

Название баттл-карты:
{battle_card_name}

Что сравниваем:
{product_name}

Компания:
{company_name}

URL источника:
{url if url else "URL не указан / использован ручной текст"}

Параметры, которые нужно заполнить:
{params_json}

Верни только валидный JSON-объект. Никакого Markdown, пояснений и текста вокруг JSON.

Формат ответа строго такой:
{{
  "Название параметра": {{
    "value": "краткое значение или Не указано",
    "evidence": "короткий фрагмент исходного текста, подтверждающий значение",
    "source_type": "page | document | manual_text | parser_metadata | not_found",
    "confidence": "высокая | средняя | низкая",
    "missing_reason": "почему данных нет, если value = Не указано"
  }}
}}

Правила:
1. Ключи верхнего уровня должны точно совпадать с названиями параметров из списка.
2. Каждый параметр должен быть объектом с полями value, evidence, source_type, confidence, missing_reason.
3. Используй страницу, скрытые DOM-блоки, FAQ/accordion, найденные документы, извлеченный текст PDF/DOCX/XLSX/CSV и ручной текст.
4. Если есть извлеченный текст из документа, считай его полноценным источником и ставь source_type = "document".
5. Если данные взяты из ручного текста, ставь source_type = "manual_text".
6. Если данных нет, value = "Не указано", source_type = "not_found", confidence = "низкая".
7. Не выдумывай значения и не используй знания вне предоставленного текста.
8. evidence должен быть коротким подтверждающим фрагментом из исходного текста. Если данных нет, evidence = "".
9. Если данные противоречивы, напиши в value: "На странице указано противоречиво: ..." и поставь confidence = "низкая".
10. Для параметра "Что не указано на странице" перечисли важные отсутствующие сведения из заданных параметров.
11. Для параметра "Статус парсинга" укажи понятный статус извлечения.
12. Не добавляй ключи, которых нет в списке параметров.

Текст для анализа:
{source_text}
""".strip()

def build_unification_prompt(
    battle_card_name: str,
    product_name: str,
    params: List[str],
    records: List[Dict[str, Any]],
) -> str:
    params_json = json.dumps(params, ensure_ascii=False, indent=2)
    records_json = json.dumps(records, ensure_ascii=False, indent=2)

    return f"""
Ты аналитик, который нормализует сравнительную таблицу.

Название баттл-карты:
{battle_card_name}

Что сравниваем:
{product_name}

Параметры таблицы:
{params_json}

Входные записи:
{records_json}

Задача:
Приведи формулировки к единому стилю, чтобы таблицу было удобно сравнивать по строкам.

Правила:
1. Верни только валидный JSON.
2. JSON должен быть объектом с ключом "records".
3. "records" должен быть массивом объектов.
4. В каждом объекте должны быть ключи:
   - "Компания"
   - все параметры из списка.
5. Не удаляй компании.
6. Не меняй факты.
7. Не выдумывай отсутствующие данные.
8. Если данных нет, оставь "Не указано".
9. Сохрани URL источника или значение "Нет URL / использован ручной текст".
10. Унифицируй только стиль и формат записи: суммы, сроки, краткость описаний.

Верни JSON строго такого вида:
{{
  "records": [
    {{
      "Компания": "...",
      "URL источника": "...",
      "...": "..."
    }}
  ]
}}
""".strip()


def maybe_unify_records_with_llm(
    battle_card_name: str,
    product_name: str,
    params: List[str],
    records: List[Dict[str, Any]],
    use_unification: bool,
    live_ui: Optional[Dict[str, Any]] = None,
    started_at: Optional[float] = None,
) -> List[Dict[str, Any]]:
    if not use_unification:
        return records

    try:
        if live_ui and started_at:
            render_live_status(
                ui=live_ui,
                status="Унификация общей таблицы",
                step="Унификация общей таблицы",
                company="Все компании",
                progress=95,
                completed=st.session_state.completed_companies,
                total=st.session_state.total_companies,
                started_at=started_at,
                last_event="Запущена финальная унификация записей.",
            )

        log("Запуск унификации общей таблицы через LLM.")

        prompt = build_unification_prompt(
            battle_card_name=battle_card_name,
            product_name=product_name,
            params=params,
            records=records,
        )

        response_text = call_llm(prompt)
        parsed = extract_json_from_text(response_text)

        unified_records = parsed.get("records", records)

        if not isinstance(unified_records, list):
            raise ValueError("Ключ records должен содержать массив.")

        normalized_records = []

        for item in unified_records:
            if not isinstance(item, dict):
                continue

            company_name = str(item.get("Компания", "")).strip()
            url = str(item.get("URL источника", "")).strip()

            if not company_name:
                company_name = "Не указано"

            normalized_record = {"Компания": company_name}

            for param in params:
                value = item.get(param, "Не указано")
                if value is None:
                    value = "Не указано"
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                normalized_record[param] = str(value).strip() or "Не указано"

            if "URL источника" in params and url:
                normalized_record["URL источника"] = url

            normalized_records.append(normalized_record)

        if normalized_records:
            log("Унификация успешно завершена.")

            if live_ui and started_at:
                render_live_status(
                    ui=live_ui,
                    status="Унификация завершена",
                    step="Формирование файла",
                    company="Все компании",
                    progress=98,
                    completed=st.session_state.completed_companies,
                    total=st.session_state.total_companies,
                    started_at=started_at,
                    last_event="Унификация успешно завершена.",
                )

            return normalized_records

        log("Унификация вернула пустой список, оставляю исходные записи.")
        return records

    except Exception as exc:
        log(f"Ошибка унификации: {repr(exc)}")
        log(traceback.format_exc())
        add_user_update("Унификация не выполнена из-за ошибки. Таблица сохранена в исходном извлечённом виде.")

        if live_ui and started_at:
            render_live_status(
                ui=live_ui,
                status="Унификация не выполнена",
                step="Формирование файла",
                company="Все компании",
                progress=98,
                completed=st.session_state.completed_companies,
                total=st.session_state.total_companies,
                started_at=started_at,
                last_event="Унификация не выполнена из-за ошибки. Использую исходные записи.",
            )

        return records


# =========================
# PIPELINE
# =========================

def run_pipeline(
    battle_card_name: str,
    product_name: str,
    selected_companies: List[Dict[str, str]],
    params: List[str],
    use_unification: bool,
    use_verification: bool = True,
    live_ui: Optional[Dict[str, Any]] = None,
    started_at: Optional[float] = None,
) -> pd.DataFrame:
    reset_runtime_state()

    if started_at is None:
        started_at = time.time()

    params = ensure_system_params(params)
    selected_companies = deduplicate_companies(selected_companies)

    if not selected_companies:
        raise ValueError("Не указано ни одной компании со ссылкой или ручным текстом.")

    if not params:
        raise ValueError("Не указаны параметры сравнения.")

    st.session_state.total_companies = len(selected_companies)
    records = []

    log("Пайплайн запущен.")
    log(f"Название баттл-карты: {battle_card_name}")
    log(f"Что сравниваем: {product_name}")
    log(f"Компаний: {len(selected_companies)}")
    log(f"Параметров: {len(params)}")

    if live_ui:
        render_live_status(
            ui=live_ui,
            status="Запущен сбор данных",
            step="Подготовка списка компаний и параметров",
            company="—",
            progress=0,
            completed=0,
            total=len(selected_companies),
            started_at=started_at,
            last_event="Список компаний и параметров подготовлен.",
        )

    for index, company in enumerate(selected_companies):
        company_name = company["name"]
        url = str(company.get("url", "")).strip()
        manual_text = str(company.get("manual_text", "")).strip()

        base_progress = int((index / len(selected_companies)) * 90)

        if live_ui:
            render_live_status(
                ui=live_ui,
                status=f"Анализ: {company_name}",
                step="Расширенный парсинг страницы",
                company=company_name,
                progress=base_progress,
                completed=st.session_state.completed_companies,
                total=st.session_state.total_companies,
                started_at=started_at,
                last_event=(
                    f"Начинаю обработку: {company_name}. "
                    f"URL: {url if url else 'не указан'}. "
                    f"Ручной текст: {'есть' if manual_text else 'нет'}."
                ),
            )

        page_result = {
            "text": "",
            "method": "",
            "status": "Нет URL",
            "error": "",
        }

        if url:
            page_result = get_page_text(
                url=url,
                company_name=company_name,
                live_ui=live_ui,
                started_at=started_at,
            )
        else:
            log(f"{company_name}: URL не указан, проверяю ручной текст.")

        source_text = page_result.get("text", "")
        parser_status = page_result.get("status", "Ошибка парсинга")
        parser_error = page_result.get("error", "")

        if not source_text and manual_text:
            source_text = clean_text(manual_text)
            parser_status = "Использован ручной текст"
            page_result["method"] = "manual_text"
            page_result["status"] = parser_status
            page_result["text"] = source_text

            log(f"{company_name}: использован ручной текст, символов: {len(source_text)}")

            if live_ui:
                render_live_status(
                    ui=live_ui,
                    status=f"Анализ: {company_name}",
                    step="Использование ручного текста",
                    company=company_name,
                    progress=min(base_progress + 10, 90),
                    completed=st.session_state.completed_companies,
                    total=st.session_state.total_companies,
                    started_at=started_at,
                    last_event=f"{company_name}: использую ручной текст пользователя. Символов: {len(source_text)}.",
                )

        if not source_text:
            log(f"{company_name}: текст страницы не получен и ручной текст не указан.")
            raw_record = {}
            parsing_status = f"Ошибка парсинга: {parser_error[:300]}" if parser_error else "Ошибка парсинга: нет текста страницы и нет ручного текста"

            normalized = normalize_structured_record_to_schema(
                raw_record=raw_record,
                company_name=company_name,
                url=url,
                params=params,
                parsing_status=parsing_status,
            )
            records.append(normalized)
            st.session_state.completed_companies += 1

            if live_ui:
                render_live_status(
                    ui=live_ui,
                    status=f"Ошибка парсинга: {company_name}",
                    step="Компания обработана",
                    company=company_name,
                    progress=min(int(((index + 1) / len(selected_companies)) * 90), 90),
                    completed=st.session_state.completed_companies,
                    total=st.session_state.total_companies,
                    started_at=started_at,
                    last_event=f"{company_name}: текст не получен ни через сайт, ни вручную. Запись добавлена со статусом ошибки.",
                )

            continue

        if live_ui:
            render_live_status(
                ui=live_ui,
                status=f"Анализ: {company_name}",
                step="Извлечение параметров через LLM",
                company=company_name,
                progress=min(base_progress + 20, 90),
                completed=st.session_state.completed_companies,
                total=st.session_state.total_companies,
                started_at=started_at,
                last_event=(
                    f"{company_name}: текст получен методом {page_result.get('method', 'unknown')}. "
                    f"Символов: {len(source_text)}. Запускаю LLM."
                ),
            )

        try:
            trimmed_text = source_text[:MAX_SOURCE_CHARS]

            if page_result.get("method") == "manual_text":
                trimmed_text = (
                    "=== РУЧНОЙ ТЕКСТ ПОЛЬЗОВАТЕЛЯ ===\n"
                    f"Компания: {company_name}\n"
                    f"URL: {url if url else 'URL не указан'}\n\n"
                    f"{trimmed_text}"
                )

            prompt = build_extraction_prompt(
                battle_card_name=battle_card_name,
                product_name=product_name,
                company_name=company_name,
                url=url,
                source_text=trimmed_text,
                params=params,
            )

            response_text = call_llm(prompt)
            raw_record = extract_json_from_text(response_text)
            raw_record = verify_record_with_llm(
                company_name=company_name,
                params=params,
                raw_record=raw_record,
                source_text=trimmed_text,
                enabled=use_verification,
            )

            if live_ui:
                render_live_status(
                    ui=live_ui,
                    status=f"Анализ: {company_name}",
                    step="Нормализация записи",
                    company=company_name,
                    progress=min(base_progress + 30, 90),
                    completed=st.session_state.completed_companies,
                    total=st.session_state.total_companies,
                    started_at=started_at,
                    last_event=f"{company_name}: LLM вернула JSON, нормализую запись под заданную схему.",
                )

            if parser_status == "Использован ручной текст":
                parsing_status = "Использован ручной текст"
            else:
                parsing_status = "Данные извлечены"
                if parser_status != "ОК":
                    parsing_status = f"Данные частично извлечены; статус парсинга: {parser_status}"

            normalized = normalize_structured_record_to_schema(
                raw_record=raw_record,
                company_name=company_name,
                url=url,
                params=params,
                parsing_status=parsing_status,
            )

            records.append(normalized)
            st.session_state.last_raw_records.append(raw_record)

            log(f"{company_name}: LLM-извлечение успешно.")

        except Exception as exc:
            log(f"{company_name}: ошибка LLM-извлечения: {repr(exc)}")
            log(traceback.format_exc())

            normalized = normalize_record_to_schema(
                raw_record={},
                company_name=company_name,
                url=url,
                params=params,
                parsing_status=f"Ошибка LLM-извлечения: {repr(exc)[:300]}",
            )
            records.append(normalized)

            add_user_update(f"По компании {company_name} возникла ошибка извлечения. Запись добавлена со статусом ошибки.")

            if live_ui:
                render_live_status(
                    ui=live_ui,
                    status=f"Ошибка LLM-извлечения: {company_name}",
                    step="Нормализация записи",
                    company=company_name,
                    progress=min(base_progress + 30, 90),
                    completed=st.session_state.completed_companies,
                    total=st.session_state.total_companies,
                    started_at=started_at,
                    last_event=f"{company_name}: ошибка LLM-извлечения, запись добавлена со статусом ошибки.",
                )

        st.session_state.completed_companies += 1

        if live_ui:
            render_live_status(
                ui=live_ui,
                status=f"Завершено: {company_name}",
                step="Компания обработана",
                company=company_name,
                progress=min(int(((index + 1) / len(selected_companies)) * 90), 90),
                completed=st.session_state.completed_companies,
                total=st.session_state.total_companies,
                started_at=started_at,
                last_event=f"Компания обработана: {company_name}.",
            )

    final_records = maybe_unify_records_with_llm(
        battle_card_name=battle_card_name,
        product_name=product_name,
        params=params,
        records=records,
        use_unification=use_unification,
        live_ui=live_ui,
        started_at=started_at,
    )

    final_records = merge_record_metadata(final_records, records, params)

    columns = ["Компания"] + params
    df = pd.DataFrame(final_records)

    for column in columns:
        if column not in df.columns:
            df[column] = "Не указано"

    ordered_columns = columns + [column for column in df.columns if column not in columns]
    df = df[ordered_columns]
    df = add_numeric_normalization_columns(df, params)

    st.session_state.last_df = df
    st.session_state.last_meta_records = final_records

    if live_ui:
        render_live_status(
            ui=live_ui,
            status="Готово",
            step="Завершено",
            company="Все компании",
            progress=100,
            completed=st.session_state.completed_companies,
            total=st.session_state.total_companies,
            started_at=started_at,
            last_event="Таблица сформирована.",
        )

    return df


# =========================
# UI: CUSTOM COMPANIES
# =========================

def add_company_row() -> None:
    st.session_state.custom_companies.append(
        {"name": "", "url": "", "manual_text": ""}
    )


def remove_empty_company_rows() -> None:
    cleaned = []

    for item in st.session_state.custom_companies:
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        manual_text = str(item.get("manual_text", "")).strip()

        if name or url or manual_text:
            cleaned.append(
                {
                    "name": name,
                    "url": url,
                    "manual_text": manual_text,
                }
            )

    if not cleaned:
        cleaned = [{"name": "", "url": "", "manual_text": ""}]

    st.session_state.custom_companies = cleaned


def render_custom_companies_editor() -> List[Dict[str, str]]:
    st.write(
        "Укажите компании / продукты и ссылки на страницы. "
        "Если сайт не парсится или условия лежат в PDF/документе, можно вставить текст вручную."
    )

    col_a, col_b = st.columns([1, 1])

    with col_a:
        if st.button("Добавить строку с компанией"):
            add_company_row()

    with col_b:
        if st.button("Удалить пустые строки"):
            remove_empty_company_rows()

    edited_companies = []

    for i, company in enumerate(st.session_state.custom_companies):
        st.markdown(f"#### Компания {i + 1}")

        cols = st.columns([1, 3])

        with cols[0]:
            name = st.text_input(
                "Компания / продукт",
                value=company.get("name", ""),
                key=f"custom_company_name_{i}",
                placeholder="Например: Сбер, Ozon, Яндекс, Wildberries",
            )

        with cols[1]:
            url = st.text_input(
                "Ссылка",
                value=company.get("url", ""),
                key=f"custom_company_url_{i}",
                placeholder="https://...",
            )

        manual_text = st.text_area(
            "Текст вручную, если страница не спарсилась или если нужно добавить условия из PDF / документа",
            value=company.get("manual_text", ""),
            key=f"custom_company_manual_text_{i}",
            height=180,
            placeholder=(
                "Можно вставить сюда текст со страницы, из PDF, правил, тарифов, условий, FAQ или других документов. "
                "Если парсер не сможет получить текст по ссылке, приложение использует этот текст. "
                "Можно также оставить ссылку пустой и работать только с ручным текстом."
            ),
        )

        edited_companies.append(
            {
                "name": name.strip(),
                "url": url.strip(),
                "manual_text": manual_text.strip(),
            }
        )

        st.divider()

    st.session_state.custom_companies = edited_companies

    return deduplicate_companies(edited_companies)


# =========================
# UI MAIN
# =========================

st.title("Battle Cards Generator")

if client is None:
    st.warning(
        "LLM-клиент не инициализирован: не заданы YANDEX_FOLDER и/или YANDEX_API_KEY. "
        "Без этих переменных приложение сможет открыть интерфейс, но не сможет извлекать данные через LLM."
    )

st.caption(
    "Расширенный парсинг запускается на любом сайте в любом режиме. "
    "Приложение использует Playwright: скроллит страницу, раскрывает Bootstrap collapse/accordion/tab через DOM, "
    "кликает по безопасным FAQ/аккордеонам/табам, собирает скрытый DOM-текст, ссылки на документы "
    "и пытается извлечь текст из PDF/DOCX/XLSX/CSV."
)

mode = st.radio(
    "Режим",
    ["Быстрый", "Расширенный"],
    horizontal=True,
)

use_unification = st.checkbox(
    "После извлечения дополнительно унифицировать общую таблицу через LLM",
    value=True,
)

use_verification = st.checkbox(
    "Повторно проверять спорные значения через LLM",
    value=True,
)

st.divider()

if mode == "Быстрый":
    st.subheader("Быстрый режим: готовые шаблоны")

    category = st.selectbox(
        "Тип продукта",
        list(PRODUCT_BANK_URLS.keys()),
    )

    battle_card_name = category
    product_name = category

    available_companies = PRODUCT_BANK_URLS[category]
    params = PARAMETER_SETS[category]

    selected_names = st.multiselect(
        "Компании",
        [company["name"] for company in available_companies],
        default=[company["name"] for company in available_companies],
    )

    selected_companies = [
        {
            "name": company["name"],
            "url": company["url"],
            "manual_text": "",
        }
        for company in available_companies
        if company["name"] in selected_names
    ]

    with st.expander("Параметры сравнения", expanded=False):
        for param in params:
            st.write(f"• {param}")

else:
    st.subheader("Расширенный режим: универсальный конструктор")

    battle_card_name = st.text_input(
        "Название баттл-карты",
        value="Моя сравнительная таблица",
        placeholder="Например: Сравнение сервисов доставки для бизнеса",
    )

    product_name = st.text_input(
        "Что сравниваем",
        value="",
        placeholder="Например: сервисы доставки, накопительные счета, CRM-системы, страховые продукты",
    )

    st.markdown("#### Параметры сравнения")

    template_name = st.selectbox(
        "Шаблон параметров",
        list(INDUSTRY_PARAMETER_TEMPLATES.keys()),
    )

    if template_name != "Свой список":
        st.session_state.custom_params_text = "\n".join(INDUSTRY_PARAMETER_TEMPLATES[template_name])

    params_text = st.text_area(
        "Введите параметры списком или текстом. Можно писать каждый параметр с новой строки, через запятую или через точку с запятой.",
        value=st.session_state.custom_params_text,
        height=260,
    )

    st.session_state.custom_params_text = params_text

    params = parse_params_from_text(params_text)
    params = ensure_system_params(params)

    st.caption(f"Распознано параметров: {len(params)}")

    with st.expander("Посмотреть распознанные параметры", expanded=False):
        for param in params:
            st.write(f"• {param}")

    st.markdown("#### Компании, ссылки и ручной текст")

    selected_companies = render_custom_companies_editor()

    if not product_name:
        product_name = battle_card_name

st.divider()

static_panel_placeholder = st.empty()

with static_panel_placeholder.container():
    render_static_runtime_panel()

st.divider()

col_run, col_info = st.columns([1, 2])

with col_run:
    run_button = st.button(
        "Запустить",
        type="primary",
        use_container_width=True,
    )

with col_info:
    st.write(
        f"Компаний к обработке: **{len(selected_companies)}**. "
        f"Параметров: **{len(params)}**."
    )

if run_button:
    static_panel_placeholder.empty()

    live_ui = init_live_ui()
    started_at = time.time()

    try:
        df = run_pipeline(
            battle_card_name=battle_card_name,
            product_name=product_name,
            selected_companies=selected_companies,
            params=params,
            use_unification=use_unification,
            use_verification=use_verification,
            live_ui=live_ui,
            started_at=started_at,
        )

        st.success("Готово. Таблица сформирована.")
        df = render_result_section(df, params, editor_key="result_editor_current")
        st.session_state.last_df = df

        csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
        excel_bytes = dataframe_to_excel_bytes(df)

        download_col1, download_col2 = st.columns(2)

        with download_col1:
            st.download_button(
                label="Скачать CSV",
                data=csv_bytes,
                file_name="battle_card.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with download_col2:
            st.download_button(
                label="Скачать Excel",
                data=excel_bytes,
                file_name="battle_card.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    except Exception as exc:
        st.error(f"Ошибка запуска: {repr(exc)}")
        log(f"Критическая ошибка запуска: {repr(exc)}")
        log(traceback.format_exc())

        if "live_ui" in locals():
            render_live_status(
                ui=live_ui,
                status="Ошибка",
                step="Завершено",
                company=st.session_state.current_company,
                progress=st.session_state.progress_value,
                completed=st.session_state.completed_companies,
                total=st.session_state.total_companies,
                started_at=started_at,
                last_event=f"Критическая ошибка: {repr(exc)}",
            )

        with st.expander("Подробности ошибки", expanded=True):
            st.code(traceback.format_exc())

if st.session_state.last_df is not None and not run_button:
    st.subheader("Последний результат")
    last_df = render_result_section(st.session_state.last_df, params, editor_key="result_editor_last")

    csv_bytes = last_df.to_csv(index=False).encode("utf-8-sig")
    excel_bytes = dataframe_to_excel_bytes(last_df)

    download_col1, download_col2 = st.columns(2)

    with download_col1:
        st.download_button(
            label="Скачать последний CSV",
            data=csv_bytes,
            file_name="battle_card.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with download_col2:
        st.download_button(
            label="Скачать последний Excel",
            data=excel_bytes,
            file_name="battle_card.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
