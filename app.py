from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

from competitive_research.cache import JsonCache
from competitive_research.config import AppConfig, ensure_directories
from competitive_research.exporters import (
    cells_to_dataframe,
    export_csv,
    export_docx,
    export_excel,
    export_markdown,
    export_pdf,
    google_sheets_payload,
)
from competitive_research.models import (
    DEFAULT_TEMPLATE_GROUPS,
    RESEARCH_TYPES,
    CompetitorInput,
    ResearchRun,
    ResearchTemplate,
)
from competitive_research.pipeline import ResearchPipeline
from competitive_research.presets import preset_competitors, preset_groups, preset_names, preset_research_type
from competitive_research.storage import ResearchStorage, diff_runs
from competitive_research.ui_components import (
    inject_workspace_css,
    render_insights,
    render_live_logs,
    render_review_table,
    template_editor,
)


st.set_page_config(
    page_title="AI конкурентный анализ",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_workspace_css()

CONFIG = AppConfig()
ensure_directories(CONFIG)
STORAGE = ResearchStorage(CONFIG)
CACHE = JsonCache(CONFIG.cache_dir)


def init_state() -> None:
    defaults = {
        "current_run": None,
        "current_progress": 0.0,
        "current_message": "Готов к запуску.",
        "run_started_at": None,
        "competitors": [
            {"name": "", "url": "", "manual_text": "", "uploaded_text": ""},
            {"name": "", "url": "", "manual_text": "", "uploaded_text": ""},
            {"name": "", "url": "", "manual_text": "", "uploaded_text": ""},
        ],
        "active_preset": "Свой список",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "preset_selector" not in st.session_state:
        st.session_state.preset_selector = st.session_state.active_preset


def extract_uploaded_text(files) -> str:
    parts: List[str] = []
    for file in files or []:
        name = file.name.lower()
        content = file.read()
        try:
            if name.endswith(".pdf"):
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(content))
                text = "\n".join(page.extract_text() or "" for page in reader.pages[:80])
            elif name.endswith(".docx"):
                from docx import Document

                document = Document(io.BytesIO(content))
                text = "\n".join(paragraph.text for paragraph in document.paragraphs)
            elif name.endswith((".html", ".htm", ".txt", ".md", ".csv")):
                text = content.decode("utf-8", errors="ignore")
            else:
                text = content.decode("utf-8", errors="ignore")
            parts.append(f"=== UPLOADED {file.name} ===\n{text}")
        except Exception as exc:
            parts.append(f"=== UPLOADED {file.name} ERROR ===\n{exc}")
    return "\n\n".join(parts)


def run_event(run: ResearchRun, stage: str, message: str, progress: float) -> None:
    st.session_state.current_run = run
    st.session_state.current_progress = progress
    st.session_state.current_message = f"{stage}: {message}"
    status_placeholder.empty()
    with status_placeholder.container():
        render_compact_runtime_status()
    logs_placeholder.empty()
    with logs_placeholder.expander("Технические логи", expanded=False):
        render_live_logs(run)


def elapsed_runtime_text() -> str:
    started_at = st.session_state.get("run_started_at")
    if not started_at:
        return "00:00"
    elapsed = int(time.time() - started_at)
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def render_compact_runtime_status() -> None:
    progress_percent = int(float(st.session_state.current_progress or 0.0) * 100)
    st.markdown(
        f"""
        <div class="runtime-line">
            <div><strong>Статус:</strong> {st.session_state.current_message}</div>
            <div class="runtime-meta">
                <span>Время: {elapsed_runtime_text()}</span>
                <span>Прогресс: {progress_percent}%</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def competitor_editor() -> List[CompetitorInput]:
    st.markdown("#### Конкуренты и резервные источники")
    competitors: List[CompetitorInput] = []
    rows = st.session_state.competitors
    for index, row in enumerate(rows):
        with st.expander(f"Конкурент {index + 1}", expanded=index < 3):
            col1, col2 = st.columns([0.8, 1.4])
            row["name"] = col1.text_input("Название", value=row.get("name", ""), key=f"name_{index}")
            row["url"] = col2.text_input("URL", value=row.get("url", ""), key=f"url_{index}")
            row["manual_text"] = st.text_area(
                "Ручной текст, если сайт не парсится",
                value=row.get("manual_text", ""),
                height=120,
                key=f"manual_{index}",
            )
            uploaded_files = st.file_uploader(
                "PDF / HTML / DOCX / TXT как резервный источник",
                type=["pdf", "html", "htm", "docx", "txt", "md", "csv"],
                accept_multiple_files=True,
                key=f"files_{index}",
            )
            row["uploaded_text"] = extract_uploaded_text(uploaded_files)
            if row["name"].strip() or row["url"].strip() or row["manual_text"].strip() or row["uploaded_text"].strip():
                competitors.append(CompetitorInput(**row))
    add_col, clean_col = st.columns(2)
    if add_col.button("Добавить конкурента", use_container_width=True):
        st.session_state.competitors.append({"name": "", "url": "", "manual_text": "", "uploaded_text": ""})
        st.rerun()
    if clean_col.button("Удалить пустые строки", use_container_width=True):
        st.session_state.competitors = [
            item
            for item in st.session_state.competitors
            if item["name"].strip() or item["url"].strip() or item["manual_text"].strip() or item["uploaded_text"].strip()
        ] or [{"name": "", "url": "", "manual_text": "", "uploaded_text": ""}]
        st.rerun()
    return competitors


def render_exports(run: ResearchRun, diff: List[Dict[str, object]]) -> None:
    st.subheader("Экспорт")
    df = cells_to_dataframe(run.cells)
    col1, col2, col3 = st.columns(3)
    col1.download_button("CSV", export_csv(df), "battle_card.csv", "text/csv", use_container_width=True)
    col2.download_button(
        "Excel",
        export_excel(df, run.insights, run.logs, diff),
        "battle_card.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    col3.download_button("Markdown", export_markdown(df, run.insights, diff), "battle_card.md", "text/markdown", use_container_width=True)
    col4, col5, col6 = st.columns(3)
    col4.download_button(
        "DOCX",
        export_docx(df, run.insights, diff),
        "battle_card.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True,
    )
    col5.download_button("PDF", export_pdf(df, run.insights, diff), "battle_card.pdf", "application/pdf", use_container_width=True)
    col6.download_button(
        "CSV для Google Sheets",
        google_sheets_payload(df).encode("utf-8-sig"),
        "google_sheets_import.csv",
        "text/csv",
        use_container_width=True,
    )
    with st.expander("JSON source of truth", expanded=False):
        st.download_button(
            "JSON исследования",
            json.dumps(run.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"),
            f"{run.run_id}.json",
            "application/json",
        )


def apply_selected_preset() -> None:
    selected = st.session_state.get("preset_selector", "Свой список")
    st.session_state.active_preset = selected
    if selected != "Свой список":
        st.session_state.competitors = preset_competitors(selected)
        st.session_state.current_message = f"Пресет выбран: {selected}"


init_state()

st.title("AI-платформа конкурентного анализа")
st.caption("Сравнительные таблицы с источниками, уверенностью, LLM-анализом, проверкой данных, версиями и экспортом.")

with st.sidebar:
    st.header("Настройка исследования")
    preset_options = ["Свой список"] + preset_names()
    st.selectbox(
        "Готовый банковский пресет",
        preset_options,
        key="preset_selector",
        on_change=apply_selected_preset,
    )
    title = st.text_input("Название исследования", value="Конкурентная таблица")
    research_type = st.selectbox("Тип исследования", RESEARCH_TYPES, index=1)
    audience = st.selectbox("Аудитория выводов", ["Руководство", "Продукт", "Продажи", "Маркетинг", "Риски / комплаенс"], index=0)
    detail_level = st.select_slider("Детализация", options=["Short", "Balanced", "Deep"], value="Balanced")
    rerun_from_stage = st.selectbox(
        "Перезапуск с этапа",
        ["Полный запуск"] + [
            "Получение URL",
            "Парсинг",
            "LLM extraction",
            "Нормализация",
            "Генерация выводов",
        ],
    )
    st.divider()
    previous_runs = STORAGE.list_runs()
    previous_options = ["Нет"] + [f"{item['run_id']} · {item['title']} · {item['updated_at']}" for item in previous_runs]
    previous_choice = st.selectbox("Сравнить с прошлой версией", previous_options)
    st.divider()
    provider_label = "OpenAI" if CONFIG.openai_api_key else "Yandex" if CONFIG.yandex_api_key else "Эвристический режим без LLM"
    st.caption(f"LLM provider: {provider_label}")

default_template = ResearchTemplate(
    name=st.session_state.active_preset if st.session_state.active_preset != "Свой список" else f"Шаблон: {research_type}",
    research_type=preset_research_type(st.session_state.active_preset) if st.session_state.active_preset != "Свой список" else research_type,
    groups=preset_groups(st.session_state.active_preset) if st.session_state.active_preset != "Свой список" else DEFAULT_TEMPLATE_GROUPS,
    audience=audience,
    detail_level=detail_level,
)

left, right = st.columns([0.38, 0.62], gap="large")

with left:
    template = template_editor(default_template)
    competitors = competitor_editor()
    run_button = st.button("Запустить исследование", type="primary", use_container_width=True)

with right:
    context_cols = st.columns(3)
    context_cols[0].caption(f"Конкурентов: {len(competitors)}")
    context_cols[1].caption(f"Параметров: {len(template.parameters)}")
    context_cols[2].caption(f"Сохранённых исследований: {len(previous_runs)}")

    status_placeholder = st.empty()
    with status_placeholder.container():
        render_compact_runtime_status()
    logs_placeholder = st.container()
    with logs_placeholder.expander("Технические логи", expanded=False):
        render_live_logs(st.session_state.current_run)

if run_button:
    st.session_state.run_started_at = time.time()
    st.session_state.current_progress = 0.0
    st.session_state.current_message = "Запуск исследования"
    previous_data = None
    if previous_choice != "Нет":
        previous_run_id = previous_choice.split(" · ", 1)[0]
        previous_data = STORAGE.load_run(previous_run_id)
    pipeline = ResearchPipeline(CONFIG, STORAGE, CACHE)
    run = pipeline.run(
        title=title,
        research_type=research_type,
        competitors=competitors,
        template=template,
        audience=audience,
        detail_level=detail_level,
        rerun_from_stage=None if rerun_from_stage == "Полный запуск" else rerun_from_stage,
        previous_run=previous_data,
        on_event=run_event,
    )
    st.session_state.current_run = run
    st.session_state.current_progress = 1.0
    st.session_state.current_message = f"Готово: исследование сохранено {run.run_id}"
    st.success(f"Исследование сохранено: {run.run_id}")

run = st.session_state.current_run
if run:
    st.divider()
    current_df = cells_to_dataframe(run.cells)
    st.subheader("Сравнительная таблица")
    st.dataframe(current_df, use_container_width=True, hide_index=True)

    edited_cells = render_review_table(run)
    with st.expander("JSON правок", expanded=False):
        st.json(edited_cells, expanded=False)

    render_insights(run.insights)

    previous_data = None
    if previous_choice != "Нет":
        previous_run_id = previous_choice.split(" · ", 1)[0]
        previous_data = STORAGE.load_run(previous_run_id)
    diff = diff_runs(previous_data or {}, run.to_dict()) if previous_data else []
    st.subheader("Версии и изменения")
    if diff:
        st.dataframe(pd.DataFrame(diff), use_container_width=True, hide_index=True)
    else:
        st.caption("Diff появится после выбора предыдущего исследования.")
    render_exports(run, diff)

with st.expander("Архитектурные заметки", expanded=False):
    st.markdown(
        """
        - Парсер, извлечение, нормализация, интерфейс, хранение и экспорт разделены по модулям.
        - Каждая ячейка хранится как JSON-доказательство: исходное значение, нормализованное значение, источник, фрагмент, уверенность, метод, время и статус.
        - LLM подключена через слой провайдеров. Если ключ не задан, приложение работает в эвристическом режиме с низкой уверенностью.
        - Исследования сохраняются как JSON-версии в `data/runs`; сравнение версий показывает добавленные, удалённые и критично изменённые значения.
        - Интерфейс не скрывает неопределённость: отсутствие данных, неоднозначность, конфликт и необходимость проверки показываются явно.
        """
    )
