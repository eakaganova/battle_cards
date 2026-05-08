# -*- coding: utf-8 -*-

import io
import json
import os
import re
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

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


# =========================
# ENV / LLM SETTINGS
# =========================

YANDEX_FOLDER = os.getenv("YANDEX_FOLDER")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_MODEL = os.getenv("YANDEX_MODEL", "gpt-oss-120b/latest")

YANDEX_BASE_URL = "https://ai.api.cloud.yandex.net/v1"

MAX_SOURCE_CHARS = 25000
REQUESTS_TIMEOUT = 8
PLAYWRIGHT_TIMEOUT = 20000


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
    "last_raw_records": [],
    "pending_manual_requests": [],
    "pipeline_context": None,
    "base_records": [],
    "manual_records": [],
    "last_columns": [],
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================
# LOGGING / UI HELPERS
# =========================

def log(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{timestamp}] {message}")


def add_user_update(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    st.session_state.user_updates.append(f"[{timestamp}] {message}")


def update_runtime_ui(
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
    st.session_state.last_raw_records = []
    st.session_state.pending_manual_requests = []
    st.session_state.pipeline_context = None
    st.session_state.base_records = []
    st.session_state.manual_records = []
    st.session_state.last_columns = []


def render_runtime_panel() -> None:
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
            for item in st.session_state.user_updates[-15:]:
                st.write(item)
        else:
            st.write("Пока нет событий.")

    with st.expander("Технические логи", expanded=False):
        if st.session_state.logs:
            for item in st.session_state.logs[-200:]:
                st.code(item)
        else:
            st.write("Пока нет логов.")


# =========================
# TEXT / JSON HELPERS
# =========================

def clean_text(text: str) -> str:
    if not text:
        return ""

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

        key = (name.lower(), url.lower())
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
    record = {
        "Компания": company_name,
    }

    lower_key_map = {
        str(key).strip().lower(): key
        for key in raw_record.keys()
    }

    for param in params:
        if param == "URL источника":
            record[param] = url
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


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Battle Card")

        workbook = writer.book
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


def build_dataframe_from_records(
    records: List[Dict[str, Any]],
    params: List[str],
) -> pd.DataFrame:
    columns = ["Компания"] + params
    df = pd.DataFrame(records)

    for column in columns:
        if column not in df.columns:
            df[column] = "Не указано"

    df = df[columns]
    return df


# =========================
# PARSERS
# =========================

def fetch_text_requests(url: str) -> str:
    session = requests.Session()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://www.google.com/",
    }

    last_error = None

    for attempt in range(2):
        try:
            response = session.get(
                url,
                headers=headers,
                timeout=REQUESTS_TIMEOUT,
                allow_redirects=True,
            )

            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
                tag.decompose()

            text = soup.get_text("\n")
            text = clean_text(text)

            return text

        except Exception as exc:
            last_error = exc
            log(f"requests attempt {attempt + 1}/2 failed for {url}: {repr(exc)}")
            time.sleep(1)

    raise last_error


def fetch_text_playwright(url: str) -> str:
    browser = None
    context = None

    try:
        log(f"Playwright: запускаю браузер для {url}")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            log(f"Playwright: браузер запущен для {url}")

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="ru-RU",
                viewport={"width": 1440, "height": 1200},
                extra_http_headers={
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                },
            )

            page = context.new_page()
            page.set_default_timeout(10000)
            page.set_default_navigation_timeout(PLAYWRIGHT_TIMEOUT)

            log(f"Playwright: открываю страницу {url}")

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=PLAYWRIGHT_TIMEOUT,
            )

            log(f"Playwright: DOM загружен для {url}")

            try:
                page.wait_for_load_state("networkidle", timeout=5000)
                log(f"Playwright: networkidle получен для {url}")
            except Exception:
                log(f"Playwright: networkidle не дождались, продолжаю для {url}")

            page.wait_for_timeout(2000)

            title = ""
            current_url = ""

            try:
                title = page.title()
            except Exception:
                title = ""

            try:
                current_url = page.url
            except Exception:
                current_url = ""

            log(f"Playwright: title='{title}', current_url='{current_url}'")

            text = page.locator("body").inner_text(timeout=8000)
            text = clean_text(text)

            log(f"Playwright: получено символов: {len(text)} для {url}")

            if not text:
                raise RuntimeError(
                    f"Playwright открыл страницу, но body пустой. "
                    f"Title: {title}. Current URL: {current_url}"
                )

            if len(text) < 300:
                raise RuntimeError(
                    f"Playwright получил слишком мало текста: {len(text)} символов. "
                    f"Title: {title}. Current URL: {current_url}. "
                    f"Текст: {text[:500]}"
                )

            return text

    except Exception as exc:
        error_text = str(exc)

        if "Executable doesn't exist" in error_text or "playwright install" in error_text:
            raise RuntimeError(
                "Playwright установлен, но браузер Chromium не скачан. "
                "В Render добавьте build.sh с командой: "
                "PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install chromium. "
                "После этого выполните Manual Deploy → Clear build cache & deploy."
            ) from exc

        raise

    finally:
        try:
            if context is not None:
                context.close()
        except Exception:
            pass

        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass


def get_page_text(url: str, company_name: str) -> Dict[str, Any]:
    result = {
        "text": "",
        "method": "",
        "status": "Ошибка парсинга",
        "error": "",
    }

    try:
        log(f"{company_name}: пробую requests: {url}")
        text = fetch_text_requests(url)

        if len(text) >= 1000:
            result["text"] = text
            result["method"] = "requests"
            result["status"] = "ОК"
            log(f"{company_name}: requests успешно, символов: {len(text)}")
            return result

        log(f"{company_name}: requests вернул слишком мало текста: {len(text)} символов")

    except Exception as exc:
        result["error"] = repr(exc)
        log(f"{company_name}: requests ошибка: {repr(exc)}")

    try:
        log(f"{company_name}: пробую Playwright: {url}")
        text = fetch_text_playwright(url)

        if len(text) >= 300:
            result["text"] = text
            result["method"] = "playwright"
            result["status"] = "ОК"
            log(f"{company_name}: Playwright успешно, символов: {len(text)}")
            return result

        result["text"] = text
        result["method"] = "playwright"
        result["status"] = "Мало текста"
        result["error"] = f"Получено мало текста: {len(text)} символов."
        log(f"{company_name}: Playwright вернул мало текста: {len(text)} символов")
        return result

    except Exception as exc:
        previous_error = result.get("error", "")
        result["error"] = f"requests error: {previous_error}; playwright error: {repr(exc)}"
        log(f"{company_name}: Playwright ошибка: {repr(exc)}")
        return result


def is_probable_blocking_error(error_text: str) -> bool:
    if not error_text:
        return False

    lowered = error_text.lower()

    blocking_markers = [
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "timeout",
        "timed out",
        "connecttimeout",
        "readtimeout",
        "captcha",
        "access denied",
        "blocked",
        "too many requests",
        "429",
        "bot",
        "antibot",
        "cloudflare",
    ]

    return any(marker in lowered for marker in blocking_markers)


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
    source_mode: str = "parsed",
) -> str:
    params_json = json.dumps(params, ensure_ascii=False, indent=2)

    if source_mode == "manual":
        source_note = (
            "Текст страницы был вставлен пользователем вручную, потому что сайт "
            "не отдал данные автоматическому парсеру."
        )
    else:
        source_note = "Текст страницы был получен автоматическим парсером."

    return f"""
Ты аналитик, который заполняет battle card / сравнительную таблицу по данным с сайта.

Задача:
Нужно извлечь из текста страницы информацию о продукте / сервисе / предложении компании и заполнить значения строго по заданным параметрам.

Название баттл-карты:
{battle_card_name}

Что сравниваем:
{product_name}

Компания:
{company_name}

URL источника:
{url}

Источник текста:
{source_note}

Параметры, которые нужно заполнить:
{params_json}

Правила:
1. Верни только валидный JSON-объект. Никакого Markdown, пояснений и текста вокруг JSON.
2. Ключи JSON должны точно совпадать с названиями параметров из списка.
3. Если на странице нет данных по параметру, укажи "Не указано".
4. Не выдумывай значения.
5. Если значение найдено, формулируй кратко, но так, чтобы смысл был понятен.
6. Если данные противоречивы, напиши: "На странице указано противоречиво: ..." и кратко поясни.
7. Для параметра "Что не указано на странице" перечисли важные отсутствующие сведения из заданных параметров.
8. Для параметра "Статус парсинга" укажи одну из формулировок:
   - "Данные извлечены"
   - "Данные частично извлечены"
   - "Данные извлечены из текста, вставленного вручную"
   - "На странице мало релевантной информации"
9. Не добавляй ключи, которых нет в списке параметров.

Текст страницы:
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
9. Сохрани URL источника.
10. Унифицируй только стиль и формат записи: например, суммы, сроки, краткость описаний.

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


def extract_record_with_llm(
    battle_card_name: str,
    product_name: str,
    company_name: str,
    url: str,
    source_text: str,
    params: List[str],
    source_mode: str,
    parsing_status: str,
) -> Dict[str, Any]:
    trimmed_text = source_text[:MAX_SOURCE_CHARS]

    prompt = build_extraction_prompt(
        battle_card_name=battle_card_name,
        product_name=product_name,
        company_name=company_name,
        url=url,
        source_text=trimmed_text,
        params=params,
        source_mode=source_mode,
    )

    response_text = call_llm(prompt)
    raw_record = extract_json_from_text(response_text)

    normalized = normalize_record_to_schema(
        raw_record=raw_record,
        company_name=company_name,
        url=url,
        params=params,
        parsing_status=parsing_status,
    )

    st.session_state.last_raw_records.append(raw_record)

    return normalized


def maybe_unify_records_with_llm(
    battle_card_name: str,
    product_name: str,
    params: List[str],
    records: List[Dict[str, Any]],
    use_unification: bool,
) -> List[Dict[str, Any]]:
    if not use_unification:
        return records

    try:
        update_runtime_ui(
            status="Унификация общей таблицы",
            step="LLM-унификация",
            company="Все компании",
            progress=95,
            user_message="Запущена унификация общей таблицы.",
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
            return normalized_records

        log("Унификация вернула пустой список, оставляю исходные записи.")
        return records

    except Exception as exc:
        log(f"Ошибка унификации: {repr(exc)}")
        log(traceback.format_exc())
        add_user_update("Унификация не выполнена из-за ошибки. Таблица сохранена в исходном извлечённом виде.")
        return records


# =========================
# PIPELINE
# =========================

def make_blocked_placeholder_record(
    company_name: str,
    url: str,
    params: List[str],
    error_text: str,
) -> Dict[str, Any]:
    if is_probable_blocking_error(error_text):
        status = (
            "Сайт заблокировал парсер или не отдал страницу автоматически. "
            "Нужно вставить текст страницы вручную."
        )
    else:
        status = (
            "Не удалось получить страницу автоматически. "
            "Можно вставить текст страницы вручную."
        )

    record = normalize_record_to_schema(
        raw_record={},
        company_name=company_name,
        url=url,
        params=params,
        parsing_status=status,
    )

    if "Что не указано на странице" in record:
        record["Что не указано на странице"] = (
            "Автоматический парсер не получил текст страницы. "
            "Для извлечения данных нужно открыть сайт вручную, скопировать текст и вставить его в приложение."
        )

    return record


def add_pending_manual_request(
    company_name: str,
    url: str,
    error_text: str,
) -> None:
    existing_keys = {
        (item.get("name", ""), item.get("url", ""))
        for item in st.session_state.pending_manual_requests
    }

    key = (company_name, url)

    if key in existing_keys:
        return

    st.session_state.pending_manual_requests.append(
        {
            "name": company_name,
            "url": url,
            "error": error_text,
            "manual_text": "",
        }
    )


def run_pipeline(
    battle_card_name: str,
    product_name: str,
    selected_companies: List[Dict[str, str]],
    params: List[str],
    use_unification: bool,
) -> pd.DataFrame:
    reset_runtime_state()

    params = ensure_system_params(params)
    selected_companies = deduplicate_companies(selected_companies)

    if not selected_companies:
        raise ValueError("Не указано ни одной компании со ссылкой или ручным текстом.")

    if not params:
        raise ValueError("Не указаны параметры сравнения.")

    st.session_state.total_companies = len(selected_companies)

    st.session_state.pipeline_context = {
        "battle_card_name": battle_card_name,
        "product_name": product_name,
        "params": params,
        "use_unification": use_unification,
    }

    st.session_state.last_columns = ["Компания"] + params

    records = []

    update_runtime_ui(
        status="Запущен сбор данных",
        step="Подготовка",
        company="—",
        progress=0,
        user_message="Пайплайн запущен.",
    )

    for index, company in enumerate(selected_companies):
        company_name = company["name"]
        url = company.get("url", "")
        manual_text = company.get("manual_text", "")

        base_progress = int((index / len(selected_companies)) * 90)

        if manual_text:
            update_runtime_ui(
                status=f"Анализ: {company_name}",
                step="LLM-извлечение из ручного текста",
                company=company_name,
                progress=base_progress,
                user_message=f"Использую текст, вставленный вручную: {company_name}.",
            )

            try:
                normalized = extract_record_with_llm(
                    battle_card_name=battle_card_name,
                    product_name=product_name,
                    company_name=company_name,
                    url=url,
                    source_text=manual_text,
                    params=params,
                    source_mode="manual",
                    parsing_status="Данные извлечены из текста, вставленного вручную",
                )
                records.append(normalized)
                log(f"{company_name}: LLM-извлечение из ручного текста успешно.")

            except Exception as exc:
                log(f"{company_name}: ошибка LLM-извлечения из ручного текста: {repr(exc)}")
                log(traceback.format_exc())

                normalized = normalize_record_to_schema(
                    raw_record={},
                    company_name=company_name,
                    url=url,
                    params=params,
                    parsing_status=f"Ошибка LLM-извлечения из ручного текста: {repr(exc)[:300]}",
                )
                records.append(normalized)

            st.session_state.completed_companies += 1
            continue

        update_runtime_ui(
            status=f"Анализ: {company_name}",
            step="Парсинг страницы",
            company=company_name,
            progress=base_progress,
            user_message=f"Парсю страницу: {company_name}.",
        )

        page_result = get_page_text(url, company_name)
        source_text = page_result.get("text", "")
        parser_status = page_result.get("status", "Ошибка парсинга")
        parser_error = page_result.get("error", "")

        if not source_text:
            log(f"{company_name}: текст страницы не получен.")

            add_pending_manual_request(
                company_name=company_name,
                url=url,
                error_text=parser_error,
            )

            placeholder = make_blocked_placeholder_record(
                company_name=company_name,
                url=url,
                params=params,
                error_text=parser_error,
            )

            records.append(placeholder)

            add_user_update(
                f"Сайт {company_name} не отдал страницу парсеру. "
                f"Нужно вставить текст вручную в блоке ниже."
            )

            st.session_state.completed_companies += 1
            continue

        update_runtime_ui(
            status=f"Анализ: {company_name}",
            step="LLM-извлечение",
            company=company_name,
            progress=min(base_progress + 10, 90),
            user_message=f"Извлекаю параметры через LLM: {company_name}.",
        )

        try:
            parsing_status = "Данные извлечены"
            if parser_status != "ОК":
                parsing_status = f"Данные частично извлечены; статус парсинга: {parser_status}"

            normalized = extract_record_with_llm(
                battle_card_name=battle_card_name,
                product_name=product_name,
                company_name=company_name,
                url=url,
                source_text=source_text,
                params=params,
                source_mode="parsed",
                parsing_status=parsing_status,
            )

            records.append(normalized)

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

        st.session_state.completed_companies += 1

        update_runtime_ui(
            status=f"Завершено: {company_name}",
            step="Компания обработана",
            company=company_name,
            progress=min(int(((index + 1) / len(selected_companies)) * 90), 90),
            user_message=f"Компания обработана: {company_name}.",
        )

    st.session_state.base_records = records

    if st.session_state.pending_manual_requests:
        final_records = records
        update_runtime_ui(
            status="Часть сайтов не отдала текст парсеру",
            step="Ожидается ручная вставка текста",
            company="Сайты с блокировкой",
            progress=90,
            user_message="Для части сайтов нужно вручную вставить текст страницы.",
        )
    else:
        final_records = maybe_unify_records_with_llm(
            battle_card_name=battle_card_name,
            product_name=product_name,
            params=params,
            records=records,
            use_unification=use_unification,
        )

        update_runtime_ui(
            status="Готово",
            step="Завершено",
            company="Все компании",
            progress=100,
            user_message="Таблица сформирована.",
        )

    df = build_dataframe_from_records(final_records, params)
    st.session_state.last_df = df

    return df


def replace_records_with_manual_results(
    base_records: List[Dict[str, Any]],
    manual_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    manual_by_company_url = {}

    for record in manual_records:
        company = str(record.get("Компания", "")).strip()
        url = str(record.get("URL источника", "")).strip()
        manual_by_company_url[(company, url)] = record

    result = []

    for record in base_records:
        company = str(record.get("Компания", "")).strip()
        url = str(record.get("URL источника", "")).strip()
        key = (company, url)

        if key in manual_by_company_url:
            result.append(manual_by_company_url[key])
        else:
            result.append(record)

    return result


def process_manual_requests() -> Optional[pd.DataFrame]:
    context = st.session_state.pipeline_context

    if not context:
        st.error("Нет контекста предыдущего запуска. Запустите сбор данных заново.")
        return None

    battle_card_name = context["battle_card_name"]
    product_name = context["product_name"]
    params = context["params"]
    use_unification = context["use_unification"]

    manual_records = []

    update_runtime_ui(
        status="Обработка вручную вставленного текста",
        step="LLM-извлечение из ручного текста",
        company="Сайты с блокировкой",
        progress=90,
        user_message="Начата обработка вручную вставленного текста.",
    )

    for item in st.session_state.pending_manual_requests:
        company_name = item.get("name", "")
        url = item.get("url", "")
        manual_text = item.get("manual_text", "")

        if not manual_text or len(manual_text.strip()) < 200:
            add_user_update(
                f"Для {company_name} текст не обработан: вставлено слишком мало текста."
            )
            continue

        try:
            update_runtime_ui(
                status=f"Обработка ручного текста: {company_name}",
                step="LLM-извлечение из ручного текста",
                company=company_name,
                progress=92,
                user_message=f"Передаю вручную вставленный текст в LLM: {company_name}.",
            )

            normalized = extract_record_with_llm(
                battle_card_name=battle_card_name,
                product_name=product_name,
                company_name=company_name,
                url=url,
                source_text=manual_text,
                params=params,
                source_mode="manual",
                parsing_status="Данные извлечены из текста, вставленного вручную",
            )

            manual_records.append(normalized)
            log(f"{company_name}: ручной текст успешно обработан через LLM.")

        except Exception as exc:
            log(f"{company_name}: ошибка обработки ручного текста: {repr(exc)}")
            log(traceback.format_exc())

            error_record = normalize_record_to_schema(
                raw_record={},
                company_name=company_name,
                url=url,
                params=params,
                parsing_status=f"Ошибка обработки ручного текста: {repr(exc)[:300]}",
            )
            manual_records.append(error_record)

    st.session_state.manual_records = manual_records

    merged_records = replace_records_with_manual_results(
        base_records=st.session_state.base_records,
        manual_records=manual_records,
    )

    final_records = maybe_unify_records_with_llm(
        battle_card_name=battle_card_name,
        product_name=product_name,
        params=params,
        records=merged_records,
        use_unification=use_unification,
    )

    df = build_dataframe_from_records(final_records, params)
    st.session_state.last_df = df

    update_runtime_ui(
        status="Готово",
        step="Завершено после ручной вставки",
        company="Все компании",
        progress=100,
        user_message="Таблица обновлена с учётом вручную вставленного текста.",
    )

    return df


# =========================
# UI: CUSTOM COMPANIES
# =========================

def add_company_row() -> None:
    st.session_state.custom_companies.append({"name": "", "url": "", "manual_text": ""})


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
    st.write("Укажите компании / продукты и ссылки на страницы, откуда нужно собрать данные.")

    col_a, col_b = st.columns([1, 1])

    with col_a:
        if st.button("Добавить строку с компанией"):
            add_company_row()

    with col_b:
        if st.button("Удалить пустые строки"):
            remove_empty_company_rows()

    edited_companies = []

    for i, company in enumerate(st.session_state.custom_companies):
        st.markdown(f"**Компания {i + 1}**")

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

        with st.expander(
            f"Ручной текст для {name or 'компании ' + str(i + 1)}",
            expanded=False,
        ):
            st.caption(
                "Это поле можно заполнить заранее, если сайт точно блокирует парсеры. "
                "Тогда приложение не будет парсить URL, а сразу передаст этот текст в LLM."
            )
            manual_text = st.text_area(
                "Текст страницы вручную",
                value=company.get("manual_text", ""),
                key=f"custom_company_manual_text_{i}",
                height=180,
                placeholder="Откройте сайт, скопируйте текст страницы и вставьте сюда.",
            )

        edited_companies.append(
            {
                "name": name.strip(),
                "url": url.strip(),
                "manual_text": manual_text.strip(),
            }
        )

    st.session_state.custom_companies = edited_companies

    return deduplicate_companies(edited_companies)


# =========================
# UI: MANUAL FALLBACK BLOCK
# =========================

def render_manual_fallback_block() -> None:
    pending = st.session_state.pending_manual_requests

    if not pending:
        return

    st.divider()

    st.error(
        "Сайт заблокировал парсер. "
        "Откройте сайт по ссылке, скопируйте текст и вставьте его сюда."
    )

    st.caption(
        "После вставки текста нажмите кнопку обработки. "
        "Приложение передаст этот текст в LLM вместо текста, который не удалось получить парсером."
    )

    updated_pending = []

    for i, item in enumerate(pending):
        company_name = item.get("name", "")
        url = item.get("url", "")
        error_text = item.get("error", "")

        with st.container(border=True):
            st.markdown(f"### {company_name}")

            if url:
                st.markdown(f"[Открыть сайт]({url})")

            with st.expander("Техническая причина", expanded=False):
                st.code(error_text or "Нет технической ошибки.")

            manual_text = st.text_area(
                "Откройте сайт по ссылке, скопируйте текст и вставьте сюда:",
                value=item.get("manual_text", ""),
                key=f"pending_manual_text_{i}_{company_name}",
                height=260,
                placeholder=(
                    "Вставьте сюда текст страницы. "
                    "Лучше копировать основной текст продукта: условия, тарифы, требования, ограничения, FAQ."
                ),
            )

            updated_item = dict(item)
            updated_item["manual_text"] = manual_text.strip()
            updated_pending.append(updated_item)

    st.session_state.pending_manual_requests = updated_pending

    process_button = st.button(
        "Обработать вставленный текст",
        type="primary",
        use_container_width=True,
    )

    if process_button:
        df = process_manual_requests()

        if df is not None:
            st.success("Вручную вставленный текст обработан. Таблица обновлена.")
            st.dataframe(df, use_container_width=True)

            csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
            excel_bytes = dataframe_to_excel_bytes(df)

            download_col1, download_col2 = st.columns(2)

            with download_col1:
                st.download_button(
                    label="Скачать обновлённый CSV",
                    data=csv_bytes,
                    file_name="battle_card.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

            with download_col2:
                st.download_button(
                    label="Скачать обновлённый Excel",
                    data=excel_bytes,
                    file_name="battle_card.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )


# =========================
# UI MAIN
# =========================

st.title("Battle Cards Generator")

if client is None:
    st.warning(
        "LLM-клиент не инициализирован: не заданы YANDEX_FOLDER и/или YANDEX_API_KEY. "
        "Без этих переменных приложение сможет открыть интерфейс, но не сможет извлекать данные через LLM."
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
        st.write(params)

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

    st.markdown("#### Компании и ссылки")

    selected_companies = render_custom_companies_editor()

    if not product_name:
        product_name = battle_card_name

st.divider()

render_runtime_panel()

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
    try:
        df = run_pipeline(
            battle_card_name=battle_card_name,
            product_name=product_name,
            selected_companies=selected_companies,
            params=params,
            use_unification=use_unification,
        )

        if st.session_state.pending_manual_requests:
            st.warning(
                "Таблица сформирована частично. "
                "Для части сайтов нужно вручную вставить текст страницы."
            )
        else:
            st.success("Готово. Таблица сформирована.")

        st.dataframe(df, use_container_width=True)

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

        with st.expander("Подробности ошибки", expanded=True):
            st.code(traceback.format_exc())

render_manual_fallback_block()

if st.session_state.last_df is not None and not run_button:
    st.subheader("Последний результат")
    st.dataframe(st.session_state.last_df, use_container_width=True)

    csv_bytes = st.session_state.last_df.to_csv(index=False).encode("utf-8-sig")
    excel_bytes = dataframe_to_excel_bytes(st.session_state.last_df)

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
