from pathlib import Path

app_code = r'''import json
import os
import re
import time
import traceback
from typing import Any

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


# =========================
# ENV
# =========================

YANDEX_FOLDER = os.getenv("YANDEX_FOLDER")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_MODEL = os.getenv("YANDEX_MODEL", "gpt-oss-120b/latest")


# =========================
# STREAMLIT CONFIG
# =========================

st.set_page_config(page_title="Battle Cards", layout="wide")


# =========================
# SESSION STATE
# =========================

if "logs" not in st.session_state:
    st.session_state.logs = []

if "status" not in st.session_state:
    st.session_state.status = "Ожидание запуска"

if "progress_value" not in st.session_state:
    st.session_state.progress_value = 0

if "progress_text" not in st.session_state:
    st.session_state.progress_text = "Выберите продукт и банки, затем запустите анализ."

if "current_bank" not in st.session_state:
    st.session_state.current_bank = "—"

if "current_step" not in st.session_state:
    st.session_state.current_step = "—"

if "completed_banks" not in st.session_state:
    st.session_state.completed_banks = 0

if "total_banks" not in st.session_state:
    st.session_state.total_banks = 0

if "user_updates" not in st.session_state:
    st.session_state.user_updates = []


# =========================
# LOGGING / STATUS
# =========================

def log(message: str) -> None:
    ts = time.strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{ts}] {message}")


def add_user_update(message: str) -> None:
    ts = time.strftime("%H:%M:%S")
    st.session_state.user_updates.append(f"[{ts}] {message}")


def update_runtime_ui(
    *,
    status: str | None = None,
    step: str | None = None,
    bank: str | None = None,
    progress: int | None = None,
    user_message: str | None = None,
) -> None:
    if status is not None:
        st.session_state.status = status

    if step is not None:
        st.session_state.current_step = step

    if bank is not None:
        st.session_state.current_bank = bank

    if progress is not None:
        st.session_state.progress_value = max(0, min(100, int(progress)))

    if user_message:
        add_user_update(user_message)

    log_parts = []

    if status:
        log_parts.append(f"status={status}")

    if bank:
        log_parts.append(f"bank={bank}")

    if step:
        log_parts.append(f"step={step}")

    if progress is not None:
        log_parts.append(f"progress={progress}%")

    if log_parts:
        log("UI UPDATE: " + " | ".join(log_parts))


def render_runtime_panel() -> None:
    st.info(st.session_state.status)

    st.progress(
        st.session_state.progress_value,
        text=f"{st.session_state.progress_value}% — {st.session_state.progress_text}",
    )

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.metric("Текущий банк", st.session_state.current_bank)

    with col_b:
        st.metric("Этап", st.session_state.current_step)

    with col_c:
        total = st.session_state.total_banks
        done = st.session_state.completed_banks
        st.metric("Готово банков", f"{done} из {total}")

    with st.expander("Что сейчас происходит", expanded=True):
        if st.session_state.user_updates:
            for item in st.session_state.user_updates[-14:]:
                st.write(item)
        else:
            st.write("После запуска здесь появятся сообщения о ходе обработки.")


@st.dialog("Технические логи", width="large")
def show_logs_dialog() -> None:
    st.caption("Логи нужны для диагностики парсинга, LLM-ответов, ошибок JSON и деплоя.")
    st.code("\n".join(st.session_state.logs[-1400:]) or "Логов пока нет.")

    if st.button("Закрыть"):
        st.rerun()


def render_logs_button() -> None:
    if st.button("Технические логи", use_container_width=True):
        show_logs_dialog()


# =========================
# ENV CHECK / LLM CLIENT
# =========================

client = None

if not YANDEX_FOLDER or not YANDEX_API_KEY:
    st.error(
        "Не заданы переменные окружения YANDEX_FOLDER и/или YANDEX_API_KEY. "
        "На Render добавь их в Environment Variables."
    )
else:
    client = openai.OpenAI(
        api_key=YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER,
    )


# =========================
# TEXT UTILS
# =========================

def normalize_text(text: str) -> str:
    if not text:
        return ""

    lines = []

    for line in text.splitlines():
        line = line.strip()
        if line:
            lines.append(line)

    deduped = []
    prev = None

    for line in lines:
        if line != prev:
            deduped.append(line)
        prev = line

    return "\n".join(deduped)


def is_bad_text(text: str) -> bool:
    if not text:
        return True

    clean = text.strip()

    if len(clean) < 1500:
        return True

    bad_fragments = [
        "Ð",
        "Ñ",
        "Рџ",
        "Р°",
        "Рµ",
        "Рё",
        "РЅ",
        "Рѕ",
        "Рґ",
        "Р»",
        "Рє",
    ]

    bad_count = sum(clean.count(fragment) for fragment in bad_fragments)

    return bad_count > 20


# =========================
# REQUESTS PARSER
# =========================

def fetch_html_requests(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    response = requests.get(url, headers=headers, timeout=40)
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() in ["iso-8859-1", "ascii"]:
        response.encoding = response.apparent_encoding

    return response.text


def extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "canvas"]):
        tag.decompose()

    return normalize_text(soup.get_text(separator="\n"))


def get_text_with_requests(url: str) -> str:
    html = fetch_html_requests(url)
    log(f"Requests HTML size: {len(html)}")

    text = extract_text_from_html(html)
    log(f"Requests extracted text size: {len(text)}")
    log(f"Requests preview:\n{text[:1200] if text else 'EMPTY'}")

    return text


# =========================
# PLAYWRIGHT PARSER
# =========================

def safe_click_locator(locator, timeout: int = 1000) -> bool:
    try:
        if locator.is_visible():
            locator.click(timeout=timeout)
            return True
    except Exception:
        return False

    return False


def close_popups_and_cookies(page) -> None:
    close_texts = [
        "Принять",
        "Принять все",
        "Понятно",
        "Хорошо",
        "Согласен",
        "Согласиться",
        "Закрыть",
        "Не сейчас",
        "ОК",
        "OK",
    ]

    for text in close_texts:
        try:
            elements = page.get_by_text(text, exact=False)
            count = elements.count()

            for i in range(min(count, 7)):
                element = elements.nth(i)

                if safe_click_locator(element, timeout=1200):
                    page.wait_for_timeout(500)
                    log(f"Closed popup/cookie by text: {text}")

        except Exception:
            pass

    close_selectors = [
        "button[aria-label='Закрыть']",
        "button[aria-label='Close']",
        "[data-testid*='close']",
        "[class*='close']",
        "[class*='Close']",
    ]

    for selector in close_selectors:
        try:
            elements = page.locator(selector)
            count = elements.count()

            for i in range(min(count, 5)):
                element = elements.nth(i)

                if safe_click_locator(element, timeout=1000):
                    page.wait_for_timeout(400)
                    log(f"Closed popup by selector: {selector}")

        except Exception:
            pass


def click_by_visible_texts(page) -> int:
    click_texts = [
        "Показать ещё",
        "Показать еще",
        "Показать больше",
        "Подробнее",
        "Развернуть",
        "Раскрыть",
        "Все условия",
        "Условия",
        "Тарифы",
        "Документы",
        "Требования",
        "Как получить",
        "Как оформить",
        "Вопросы и ответы",
        "Часто задаваемые вопросы",
        "FAQ",
        "Ещё",
        "Еще",
        "Смотреть все",
        "Смотреть ещё",
        "Смотреть еще",
        "Читать далее",
        "Развернуть все",
    ]

    clicked_total = 0

    for text in click_texts:
        try:
            elements = page.get_by_text(text, exact=False)
            count = elements.count()

            for i in range(min(count, 12)):
                element = elements.nth(i)

                if safe_click_locator(element, timeout=1200):
                    clicked_total += 1
                    page.wait_for_timeout(500)
                    log(f"Clicked by text: {text}")

        except Exception:
            pass

    return clicked_total


def click_accordion_selectors(page) -> int:
    selectors = [
        "summary",
        "[role='button']",
        "[aria-expanded='false']",
        "button",
        "[class*='accordion']",
        "[class*='Accordion']",
        "[class*='spoiler']",
        "[class*='Spoiler']",
        "[class*='collapse']",
        "[class*='Collapse']",
        "[class*='faq']",
        "[class*='Faq']",
    ]

    skip_words = [
        "оформить",
        "оставить заявку",
        "получить кредит",
        "войти",
        "личный кабинет",
        "скачать",
        "позвонить",
    ]

    clicked_total = 0

    for selector in selectors:
        try:
            elements = page.locator(selector)
            count = elements.count()

            for i in range(min(count, 45)):
                element = elements.nth(i)

                try:
                    element_text = element.inner_text(timeout=500).strip().lower()
                except Exception:
                    element_text = ""

                if any(word in element_text for word in skip_words):
                    continue

                if safe_click_locator(element, timeout=900):
                    clicked_total += 1
                    page.wait_for_timeout(250)

        except Exception:
            pass

    if clicked_total:
        log(f"Clicked accordion-like elements: {clicked_total}")

    return clicked_total


def scroll_page(page, steps: int = 6, pixels: int = 2200) -> None:
    for _ in range(steps):
        page.mouse.wheel(0, pixels)
        page.wait_for_timeout(700)


def fetch_text_playwright(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-setuid-sandbox",
            ],
        )

        context = browser.new_context(
            locale="ru-RU",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 1400},
            ignore_https_errors=True,
        )

        page = context.new_page()
        page.set_default_timeout(10000)

        log("Playwright: opening page")

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            log("Playwright: networkidle timeout, continue anyway")

        close_popups_and_cookies(page)
        scroll_page(page, steps=5, pixels=2200)
        close_popups_and_cookies(page)

        click_by_visible_texts(page)
        click_accordion_selectors(page)

        for round_num in range(3):
            log(f"Playwright interaction round: {round_num + 1}")

            scroll_page(page, steps=3, pixels=2600)
            close_popups_and_cookies(page)

            clicked_texts = click_by_visible_texts(page)
            clicked_accordions = click_accordion_selectors(page)

            log(
                f"Round {round_num + 1}: "
                f"clicked_texts={clicked_texts}, "
                f"clicked_accordions={clicked_accordions}"
            )

        try:
            text = page.locator("body").inner_text(timeout=15000)
        except Exception:
            html = page.content()
            text = extract_text_from_html(html)

        context.close()
        browser.close()

        return normalize_text(text)


def get_page_text(url: str, bank_name: str) -> str:
    text = ""

    try:
        update_runtime_ui(
            bank=bank_name,
            step="Быстрый парсинг",
            status=f"Пробую быстро получить текст страницы: {bank_name}",
            user_message=f"{bank_name}: пробую быстрый парсинг страницы.",
        )

        text = get_text_with_requests(url)
        text = normalize_text(text)

    except Exception:
        log("Requests parser error")
        log(traceback.format_exc())

    if is_bad_text(text):
        log("Requests text is weak. Trying Playwright browser parser.")

        try:
            update_runtime_ui(
                bank=bank_name,
                step="Браузерный парсинг",
                status=f"Быстрого парсинга недостаточно. Открываю страницу в браузере: {bank_name}",
                user_message=f"{bank_name}: быстрый парсинг дал мало текста, запускаю браузерный режим с прокруткой и кликами.",
            )

            text = fetch_text_playwright(url)
            log(f"Playwright extracted text size: {len(text)}")
            log(f"Playwright preview:\n{text[:1800] if text else 'EMPTY'}")

        except Exception:
            log("Playwright parser error")
            log(traceback.format_exc())

    else:
        log("Requests parser result accepted")
        add_user_update(f"{bank_name}: текст страницы получен быстрым способом.")

    return text


# =========================
# FIRST LAYER: EXTRACTION PROMPT
# =========================

def get_parameters(battle_card_type: str) -> list[str]:
    return PARAMETER_SETS[battle_card_type]


def build_extraction_prompt(
    battle_card_type: str,
    bank_name: str,
    url: str,
    source_text: str,
) -> str:
    parameters = get_parameters(battle_card_type)

    return f"""
ТЫ — аналитик по банковским продуктам.

ЗАДАЧА:
Извлечь параметры продукта из текста страницы банка.

ТИП ПРОДУКТА:
{battle_card_type}

БАНК:
{bank_name}

URL:
{url}

ПАРАМЕТРЫ ДЛЯ ИЗВЛЕЧЕНИЯ:
{json.dumps(parameters, ensure_ascii=False, indent=2)}

СТРОГИЕ ПРАВИЛА:
- Используй только текст источника ниже.
- Не додумывай информацию.
- Не используй внешние знания.
- Если информации нет, пиши: "Не указано".
- Если информация указана косвенно, пиши: "Упоминается косвенно: ..." и объясни, на основании какого фрагмента.
- Если на странице есть диапазон, сохрани диапазон.
- Если есть условия типа "от", "до", "при выполнении условий", обязательно сохрани эти оговорки.
- Не превращай "от 5%" в "5%".
- Не делай вывод о выгодности продукта.
- Верни только JSON без Markdown, без пояснений, без ```.

ФОРМАТ JSON:
{{
  "Название банка": "{bank_name}",
  "URL источника": "{url}",
  "Процентная ставка": "...",
  "ПСК": "...",
  "...": "..."
}}

ТЕКСТ ИСТОЧНИКА:
{source_text}
"""


# =========================
# SECOND LAYER: UNIFICATION PROMPT
# =========================

def dataframe_to_markdown(df: pd.DataFrame) -> str:
    """
    Не используем df.to_markdown(), чтобы не требовать отдельный пакет tabulate.
    """
    safe_df = df.fillna("Не указано").astype(str)

    columns = list(safe_df.columns)

    def clean_cell(value: str) -> str:
        value = str(value)
        value = value.replace("\n", "<br>")
        value = value.replace("|", "\\|")
        return value

    header = "| " + " | ".join(clean_cell(col) for col in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"

    rows = []

    for _, row in safe_df.iterrows():
        rows.append(
            "| " + " | ".join(clean_cell(row[col]) for col in columns) + " |"
        )

    return "\n".join([header, separator] + rows)


def build_unification_prompt(markdown_table: str) -> str:
    return f"""
### 🎯 Цель:

Унифицировать формулировки условий кредита в таблице, где:

* строки — параметры кредита, например ставка, сумма, срок;
* столбцы — названия банков;
* ячейки — текстовые описания условий.

---

### ✅ Что нужно сделать:

Для каждой ячейки:

1. Сохрани только главное:
   * числа;
   * диапазоны;
   * формулировки условий;
   * критически важные уточнения.

2. Удаляй лишние слова:
   * "годовых";
   * "рублей";
   * "в расчет включены";
   * "уточнение по материалам";
   * "на странице продукта";
   * "источник данных";
   * "по данным банка";
   * и другие шумовые формулировки.

3. Соблюдай лаконичность.
   Преобразуй всё к единому, предельно краткому стилю без потери ключевой информации.

---

### 🧾 Примеры преобразований:

| Было | Стало |
|---|---|
| От 21,9% до 33,9% годовых | 21,9%-33,9% |
| До 180 месяцев (15 лет) | до 15 лет |
| «От 21 года» | от 21 года |
| 30 000 000 ₽, но не более 70% от оценки | до 30 млн; ≤70% |
| Нецелевой кредит «на любые цели» | Нецелевой |
| Уточнение по материалам банка: при оформлении «услуги по снижению ставки» 12,3%–22,9% | 12,3%-22,9%; есть снижение ставки |
| квартиры, апартаменты. Не принимаются: частный дом, дача | квартиры, апартаменты |
| упоминается косвенно: допускаются объекты в ЗАТО | допускаются объекты в ЗАТО |
| Ежемесячные аннуитетные равные платежи; график фиксирует даты | Ежемесячные аннуитетные равные платежи |

---

### 🧱 Структура вывода:

* Сохрани структуру таблицы: строки — параметры, столбцы — банки.
* Формат вывода: таблица в Markdown.
* Не сокращай названия параметров в первом столбце.
* Максимально сожми содержимое ячеек.
* Не добавляй новые данные.
* Не меняй факты.
* Не удаляй строки и столбцы.
* Если данные отсутствуют или указаны как НД, оставь "Не указано".
* Верни только Markdown-таблицу без пояснений, без вступления и без ```.

---

### 📌 Дополнительно:

Если есть несколько программ с разными ставками, оставь только диапазон и краткое пояснение, например:
`19,9%-33,9%; разные программы`
или
`12,3%-32,9%; есть снижение ставки`.

---

### ТАБЛИЦА ДЛЯ УНИФИКАЦИИ:

{markdown_table}
"""


# =========================
# LLM / JSON
# =========================

def extract_llm_text(response) -> str | None:
    try:
        if hasattr(response, "output_text") and response.output_text:
            return response.output_text

        if hasattr(response, "output") and response.output:
            for item in response.output:
                if hasattr(item, "content") and item.content:
                    for content in item.content:
                        if hasattr(content, "text") and content.text:
                            return content.text

    except Exception:
        return None

    return None


def call_llm(prompt: str, max_output_tokens: int = 3000, temperature: float = 0.1):
    if client is None:
        raise RuntimeError("LLM client is not initialized. Check YANDEX_FOLDER and YANDEX_API_KEY.")

    return client.responses.create(
        model=f"gpt://{YANDEX_FOLDER}/{YANDEX_MODEL}",
        temperature=temperature,
        input=prompt,
        max_output_tokens=max_output_tokens,
    )


def parse_json_from_llm(raw_text: str) -> dict[str, Any]:
    if not raw_text:
        raise ValueError("Пустой ответ LLM")

    cleaned = raw_text.strip()

    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)

    if not match:
        raise ValueError(f"Не найден JSON в ответе LLM: {cleaned[:500]}")

    parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise ValueError("JSON должен быть объектом")

    return parsed


def unify_table_with_llm(df: pd.DataFrame) -> str:
    markdown_table = dataframe_to_markdown(df)

    prompt = build_unification_prompt(markdown_table)

    log(f"Unification markdown size: {len(markdown_table)}")
    log(f"Unification prompt size: {len(prompt)}")

    response = call_llm(
        prompt=prompt,
        max_output_tokens=6000,
        temperature=0.1,
    )

    unified_table = extract_llm_text(response)

    if not unified_table:
        raise ValueError("LLM вернула пустую таблицу унификации")

    unified_table = unified_table.strip()
    unified_table = re.sub(r"^```markdown\s*", "", unified_table, flags=re.IGNORECASE)
    unified_table = re.sub(r"^```\s*", "", unified_table)
    unified_table = re.sub(r"\s*```$", "", unified_table)

    log(f"Unified table preview:\n{unified_table[:1500]}")

    return unified_table


# =========================
# RECORDS / TABLES
# =========================

def normalize_bank_record(
    battle_card_type: str,
    bank_name: str,
    bank_url: str,
    parsed: dict[str, Any],
    status: str,
) -> dict[str, str]:
    parameters = get_parameters(battle_card_type)

    record = {
        "Банк": bank_name,
    }

    for parameter in parameters:
        value = parsed.get(parameter, "Не указано")

        if value is None or value == "":
            value = "Не указано"

        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)

        record[parameter] = str(value)

    record["URL источника"] = bank_url
    record["Статус парсинга"] = status

    return record


def make_error_record(
    battle_card_type: str,
    bank_name: str,
    bank_url: str,
    status: str,
) -> dict[str, str]:
    parameters = get_parameters(battle_card_type)

    record = {
        "Банк": bank_name,
    }

    for parameter in parameters:
        record[parameter] = "Не указано"

    record["URL источника"] = bank_url
    record["Статус парсинга"] = status

    return record


def build_comparison_table(records: list[dict[str, str]], battle_card_type: str) -> pd.DataFrame:
    """
    Возвращает таблицу в формате:
    строки = параметры,
    столбцы = банки.
    """
    parameters = get_parameters(battle_card_type)

    source_df = pd.DataFrame(records)

    if "Банк" not in source_df.columns:
        source_df["Банк"] = "Не указано"

    for parameter in parameters:
        if parameter not in source_df.columns:
            source_df[parameter] = "Не указано"

    rows = []

    for parameter in parameters:
        row = {"Параметр": parameter}

        for _, record in source_df.iterrows():
            bank_name = str(record.get("Банк", "Не указано"))
            value = record.get(parameter, "Не указано")

            if pd.isna(value) or value == "":
                value = "Не указано"

            row[bank_name] = str(value)

        rows.append(row)

    comparison_df = pd.DataFrame(rows)

    bank_columns = [str(record.get("Банк", "Не указано")) for record in records]
    columns = ["Параметр"] + bank_columns

    for column in columns:
        if column not in comparison_df.columns:
            comparison_df[column] = "Не указано"

    comparison_df = comparison_df[columns]

    return comparison_df


# =========================
# PIPELINE
# =========================

def run_pipeline(battle_card_type: str, selected_banks: list[dict]) -> tuple[pd.DataFrame, str] | None:
    try:
        st.session_state.logs = []
        st.session_state.user_updates = []
        st.session_state.completed_banks = 0
        st.session_state.total_banks = len(selected_banks)
        st.session_state.progress_value = 0
        st.session_state.progress_text = "Запускаю обработку."

        update_runtime_ui(
            status="Запуск анализа. Сначала соберу тексты страниц, затем извлеку параметры и соберу таблицу.",
            step="Запуск",
            bank="—",
            progress=0,
            user_message="Анализ запущен. Итогом будет одна сравнительная таблица по выбранным банкам.",
        )

        records = []
        total_banks = len(selected_banks)

        for index, bank in enumerate(selected_banks, start=1):
            bank_name = bank["name"]
            bank_url = bank["url"]

            base_progress = int(((index - 1) / max(total_banks, 1)) * 85)
            parse_progress = min(base_progress + int(25 / max(total_banks, 1)), 90)
            llm_progress = min(base_progress + int(55 / max(total_banks, 1)), 95)

            try:
                st.session_state.progress_text = f"{bank_name}: сбор текста страницы."

                update_runtime_ui(
                    status=f"Обрабатываю {bank_name}: собираю текст страницы.",
                    step="Сбор текста",
                    bank=bank_name,
                    progress=base_progress,
                    user_message=f"{bank_name}: начал обработку страницы.",
                )

                log("=" * 80)
                log(f"START: {bank_name}")
                log(f"URL: {bank_url}")

                page_text = get_page_text(bank_url, bank_name)
                page_text = normalize_text(page_text)

                text_size = len(page_text) if page_text else 0
                log(f"Final extracted text size: {text_size}")

                st.session_state.progress_text = f"{bank_name}: текст собран, проверяю объём."

                update_runtime_ui(
                    status=f"{bank_name}: текст страницы собран, проверяю пригодность для анализа.",
                    step="Проверка текста",
                    bank=bank_name,
                    progress=parse_progress,
                    user_message=f"{bank_name}: извлечено {text_size} символов текста.",
                )

                if not page_text or len(page_text.strip()) < 1000:
                    log(f"TEXT TOO SMALL AFTER ALL PARSERS: {bank_name} ({text_size})")

                    records.append(
                        make_error_record(
                            battle_card_type=battle_card_type,
                            bank_name=bank_name,
                            bank_url=bank_url,
                            status=f"Недостаточно текста: {text_size} символов",
                        )
                    )

                    st.session_state.completed_banks += 1
                    add_user_update(
                        f"{bank_name}: данных недостаточно, банк добавлен в таблицу со статусом ошибки."
                    )
                    continue

                limited_text = page_text[:70000]

                if len(page_text) > len(limited_text):
                    log(f"Text truncated for prompt: {len(page_text)} -> {len(limited_text)}")

                st.session_state.progress_text = f"{bank_name}: извлекаю параметры через LLM."

                update_runtime_ui(
                    status=f"{bank_name}: отправляю текст в LLM для извлечения параметров.",
                    step="LLM-анализ",
                    bank=bank_name,
                    progress=llm_progress,
                    user_message=f"{bank_name}: текст передан в LLM, извлекаются параметры продукта.",
                )

                prompt = build_prompt(
                    battle_card_type=battle_card_type,
                    bank_name=bank_name,
                    url=bank_url,
                    source_text=limited_text,
                )

                log(f"Prompt size: {len(prompt)}")

                response = call_llm(prompt)
                log("LLM response received")

                raw_text = extract_llm_text(response)

                if not raw_text:
                    log(f"EMPTY OUTPUT: {bank_name}")
                    log(str(response))

                    records.append(
                        make_error_record(
                            battle_card_type=battle_card_type,
                            bank_name=bank_name,
                            bank_url=bank_url,
                            status="LLM вернула пустой ответ",
                        )
                    )

                    st.session_state.completed_banks += 1
                    add_user_update(
                        f"{bank_name}: LLM вернула пустой ответ, банк добавлен в таблицу со статусом ошибки."
                    )
                    continue

                log(f"LLM raw preview:\n{raw_text[:1000]}")

                st.session_state.progress_text = f"{bank_name}: нормализую ответ и добавляю строку в таблицу."

                update_runtime_ui(
                    status=f"{bank_name}: ответ LLM получен, собираю строку сравнительной таблицы.",
                    step="Сбор таблицы",
                    bank=bank_name,
                    progress=min(llm_progress + 5, 97),
                    user_message=f"{bank_name}: параметры получены, добавляю банк в итоговую таблицу.",
                )

                parsed = parse_json_from_llm(raw_text)

                record = normalize_bank_record(
                    battle_card_type=battle_card_type,
                    bank_name=bank_name,
                    bank_url=bank_url,
                    parsed=parsed,
                    status="ОК",
                )

                records.append(record)
                st.session_state.completed_banks += 1

            except Exception:
                err = traceback.format_exc()

                log(f"ERROR BANK: {bank_name}")
                log(err)

                records.append(
                    make_error_record(
                        battle_card_type=battle_card_type,
                        bank_name=bank_name,
                        bank_url=bank_url,
                        status=f"Ошибка: {err[-700:]}",
                    )
                )

                st.session_state.completed_banks += 1
                add_user_update(
                    f"{bank_name}: возникла ошибка, банк добавлен в таблицу со статусом ошибки."
                )

            finally:
                bank_done_progress = int((index / max(total_banks, 1)) * 85)
                st.session_state.progress_text = f"Обработано банков: {index} из {total_banks}."

                update_runtime_ui(
                    status=f"Завершил обработку банка: {bank_name}.",
                    step="Банк завершён",
                    bank=bank_name,
                    progress=bank_done_progress,
                )

        if not records:
            log("NO RECORDS")
            return None

        update_runtime_ui(
            status="Формирую первичную сравнительную таблицу.",
            step="Формирование таблицы",
            bank="—",
            progress=90,
            user_message="Все выбранные банки обработаны. Формирую первичную таблицу параметров.",
        )

        comparison_df = build_comparison_table(records, battle_card_type)

        update_runtime_ui(
            status="Унифицирую формулировки в таблице.",
            step="Унификация формулировок",
            bank="—",
            progress=95,
            user_message="Запущен второй LLM-проход: формулировки приводятся к единому краткому стилю.",
        )

        unified_markdown_table = unify_table_with_llm(comparison_df)

        st.session_state.progress_text = "Готово."

        update_runtime_ui(
            status="Готово. Унифицированная сравнительная таблица сформирована.",
            step="Готово",
            bank="—",
            progress=100,
            user_message="Готово: таблица сформирована и унифицирована.",
        )

        return comparison_df, unified_markdown_table

    except Exception:
        log("PIPELINE ERROR")
        log(traceback.format_exc())
        return None


# =========================
# UI
# =========================

top_left, top_right = st.columns([0.82, 0.18])

with top_left:
    st.title("Battle Cards Generator")

with top_right:
    render_logs_button()

st.caption(
    "На выходе формируется одна общая сравнительная таблица: параметры в строках, банки в столбцах. "
    "После первичного извлечения запускается второй LLM-проход для унификации формулировок."
)

if client is None:
    st.stop()

battle_card_type = st.selectbox(
    "Тип баттл-карты",
    list(PRODUCT_BANK_URLS.keys()),
)

banks = PRODUCT_BANK_URLS[battle_card_type]

selected_bank_names = st.multiselect(
    "Банки",
    [b["name"] for b in banks],
    default=[b["name"] for b in banks],
)

selected_banks = [
    b
    for b in banks
    if b["name"] in selected_bank_names
]

with st.expander("Текущие URL"):
    for bank in selected_banks:
        st.write(f"**{bank['name']}** — {bank['url']}")

render_runtime_panel()

if st.button("Запустить анализ", type="primary"):
    if not selected_banks:
        st.error("Выбери хотя бы один банк.")
    else:
        result = run_pipeline(battle_card_type, selected_banks)

        if result is not None:
            result_df, unified_markdown_table = result

            st.success("Готово")

            st.subheader("Унифицированная сравнительная таблица")
            st.markdown(unified_markdown_table)

            csv_bytes = result_df.to_csv(index=False).encode("utf-8-sig")

            st.download_button(
                label="Скачать CSV с исходной структурированной таблицей",
                data=csv_bytes,
                file_name="bank_comparison_parameters_by_banks.csv",
                mime="text/csv",
            )

            with st.expander("Показать исходную таблицу до унификации"):
                st.dataframe(result_df, use_container_width=True, hide_index=True)

        else:
            st.error("Получен пустой результат. Открой технические логи справа вверху.")
