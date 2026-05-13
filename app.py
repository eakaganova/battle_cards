from __future__ import annotations

import io
import json
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
from competitive_research.storage import ResearchStorage, diff_runs
from competitive_research.ui_components import (
    inject_workspace_css,
    render_insights,
    render_live_logs,
    render_review_table,
    render_stage_timeline,
    template_editor,
)


st.set_page_config(
    page_title="Competitive AI Research",
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
        "competitors": [
            {"name": "", "url": "", "manual_text": "", "uploaded_text": ""},
            {"name": "", "url": "", "manual_text": "", "uploaded_text": ""},
            {"name": "", "url": "", "manual_text": "", "uploaded_text": ""},
        ],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


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
    progress_placeholder.progress(progress, text=st.session_state.current_message)
    timeline_placeholder.empty()
    with timeline_placeholder.container():
        render_stage_timeline(run)
    logs_placeholder.empty()
    with logs_placeholder.container():
        render_live_logs(run)


def competitor_editor() -> List[CompetitorInput]:
    st.markdown("#### Competitors and fallback sources")
    competitors: List[CompetitorInput] = []
    rows = st.session_state.competitors
    for index, row in enumerate(rows):
        with st.expander(f"Competitor {index + 1}", expanded=index < 3):
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
                "PDF / HTML / DOCX / TXT fallback",
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
    st.subheader("Export system")
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
        "Google Sheets CSV payload",
        google_sheets_payload(df).encode("utf-8-sig"),
        "google_sheets_import.csv",
        "text/csv",
        use_container_width=True,
    )
    with st.expander("JSON source of truth", expanded=False):
        st.download_button(
            "Research JSON",
            json.dumps(run.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"),
            f"{run.run_id}.json",
            "application/json",
        )


init_state()

st.title("Competitive AI Research Platform")
st.caption("Evidence-first battle-cards with visible pipeline, parser diagnostics, LLM extraction, review, versioning and exports.")

with st.sidebar:
    st.header("Research setup")
    title = st.text_input("Название исследования", value="Competitive battle-card")
    research_type = st.selectbox("Тип исследования", RESEARCH_TYPES, index=1)
    audience = st.selectbox("Аудитория выводов", ["Executive", "Product", "Sales", "Marketing", "Risk / Compliance"], index=0)
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
    provider_label = "OpenAI" if CONFIG.openai_api_key else "Yandex" if CONFIG.yandex_api_key else "Offline heuristic fallback"
    st.caption(f"LLM provider: {provider_label}")

default_template = ResearchTemplate(
    name=f"{research_type} template",
    research_type=research_type,
    groups=DEFAULT_TEMPLATE_GROUPS,
    audience=audience,
    detail_level=detail_level,
)

left, right = st.columns([0.38, 0.62], gap="large")

with left:
    template = template_editor(default_template)
    competitors = competitor_editor()
    run_button = st.button("Запустить research pipeline", type="primary", use_container_width=True)

with right:
    metric_cols = st.columns(4)
    metric_cols[0].metric("Competitors", len(competitors))
    metric_cols[1].metric("Parameters", len(template.parameters))
    metric_cols[2].metric("Saved runs", len(previous_runs))
    metric_cols[3].metric("Pipeline stages", 14)

    progress_placeholder = st.empty()
    progress_placeholder.progress(st.session_state.current_progress, text=st.session_state.current_message)
    timeline_placeholder = st.container()
    with timeline_placeholder:
        render_stage_timeline(st.session_state.current_run)
    logs_placeholder = st.container()
    with logs_placeholder:
        render_live_logs(st.session_state.current_run)

if run_button:
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
    st.success(f"Исследование сохранено: {run.run_id}")

run = st.session_state.current_run
if run:
    st.divider()
    current_df = cells_to_dataframe(run.cells)
    st.subheader("Battle-card")
    st.dataframe(current_df, use_container_width=True, hide_index=True)

    edited_cells = render_review_table(run)
    with st.expander("Edited review JSON", expanded=False):
        st.json(edited_cells, expanded=False)

    render_insights(run.insights)

    previous_data = None
    if previous_choice != "Нет":
        previous_run_id = previous_choice.split(" · ", 1)[0]
        previous_data = STORAGE.load_run(previous_run_id)
    diff = diff_runs(previous_data or {}, run.to_dict()) if previous_data else []
    st.subheader("Versioning and change tracking")
    if diff:
        st.dataframe(pd.DataFrame(diff), use_container_width=True, hide_index=True)
    else:
        st.caption("Diff появится после выбора предыдущего исследования.")
    render_exports(run, diff)

with st.expander("Architecture notes", expanded=False):
    st.markdown(
        """
        - Parser, extraction, normalization, UI, storage and export live in separate modules.
        - Every table cell is JSON-first evidence: raw value, normalized value, source, fragment, confidence, method, timestamp and status.
        - LLM is behind a provider abstraction. With no API key the app still runs in low-confidence heuristic mode.
        - Saved runs are immutable JSON versions under `data/runs`; diff highlights added, removed and critical changed values.
        - The UI never hides uncertainty: missing, ambiguous, conflicting and needs_review are first-class statuses.
        """
    )
