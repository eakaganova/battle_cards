from __future__ import annotations

import html
import io
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

from competitive_research.cache import JsonCache
from competitive_research.config import AppConfig, ensure_directories
from competitive_research.exporters import (
    cells_to_dataframe,
    cells_to_evidence_dataframe,
    export_csv,
    export_docx,
    export_excel,
    export_markdown,
    export_pdf,
    google_sheets_payload,
)
from competitive_research.models import (
    DEFAULT_TEMPLATE_GROUPS,
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
DRAFT_PATH = CONFIG.data_dir / "draft_state.json"


def load_draft_state() -> Dict[str, object]:
    if not DRAFT_PATH.exists():
        return {}
    try:
        return json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_draft_state() -> None:
    payload = {
        "competitors": st.session_state.get("competitors", []),
        "active_preset": st.session_state.get("active_preset", "Свой список"),
        "template_groups": st.session_state.get("template_groups", DEFAULT_TEMPLATE_GROUPS),
        "preset_selector": st.session_state.get("preset_selector", "Свой список"),
    }
    DRAFT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def init_state() -> None:
    draft = load_draft_state()
    defaults = {
        "current_run": None,
        "current_progress": 0.0,
        "current_message": "Готов к запуску.",
        "current_last_event_at": None,
        "last_autosave_at": 0.0,
        "run_started_at": None,
        "is_running": False,
        "competitors": [
            {"name": "", "url": "", "manual_text": "", "uploaded_text": ""},
            {"name": "", "url": "", "manual_text": "", "uploaded_text": ""},
            {"name": "", "url": "", "manual_text": "", "uploaded_text": ""},
        ],
        "active_preset": "Свой список",
        "template_groups": deepcopy(DEFAULT_TEMPLATE_GROUPS),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = draft.get(key, value)
    if "preset_selector" not in st.session_state:
        st.session_state.preset_selector = draft.get("preset_selector", st.session_state.active_preset)


def reset_template_widget_state() -> None:
    for key in list(st.session_state.keys()):
        if str(key).startswith("group_"):
            del st.session_state[key]


def sync_competitor_rows_from_widgets() -> None:
    for index, row in enumerate(st.session_state.competitors):
        manual_key = f"manual_{index}"
        if manual_key in st.session_state:
            row["manual_text"] = st.session_state.get(manual_key, "")
    save_draft_state()


def compact_competitor_rows() -> None:
    sync_competitor_rows_from_widgets()
    kept = []
    for row in st.session_state.competitors:
        normalized = {
            "name": str(row.get("name", "")),
            "url": str(row.get("url", "")),
            "manual_text": str(row.get("manual_text", "")),
            "uploaded_text": str(row.get("uploaded_text", "")),
        }
        if any(value.strip() for value in normalized.values()):
            kept.append(normalized)
    queue_competitor_rows(kept or [empty_competitor_row()])


def has_filled_competitor_rows(rows: List[Dict[str, str]]) -> bool:
    for row in rows:
        if (
            row.get("name", "").strip()
            or row.get("url", "").strip()
            or row.get("manual_text", "").strip()
            or row.get("uploaded_text", "").strip()
        ):
            return True
    return False


def extract_uploaded_text(files) -> str:
    parts: List[str] = []
    for file in files or []:
        name = file.name.lower()
        try:
            file.seek(0)
        except Exception:
            pass
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
    st.session_state.current_last_event_at = time.time()
    if time.time() - float(st.session_state.get("last_autosave_at", 0.0) or 0.0) >= 10:
        try:
            STORAGE.save_run(run)
            st.session_state.last_autosave_at = time.time()
        except Exception:
            pass
    status_placeholder.empty()
    with status_placeholder.container():
        render_compact_runtime_status()
    logs_content_placeholder.empty()
    with logs_content_placeholder.container():
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
    last_event_at = st.session_state.get("current_last_event_at")
    last_event_text = "нет"
    if last_event_at:
        seconds_ago = max(0, int(time.time() - last_event_at))
        last_event_text = f"{seconds_ago} сек. назад"
    st.markdown(
        f"""
        <div class="runtime-line">
            <div><strong>Статус:</strong> {st.session_state.current_message}</div>
            <div class="runtime-meta">
                <span>Время: {elapsed_runtime_text()}</span>
                <span>Прогресс: {progress_percent}%</span>
                <span>Последний сигнал: {last_event_text}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def competitor_editor() -> List[CompetitorInput]:
    st.markdown('<div class="panel-title">Компании и источники</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="panel-caption">Название и URL редактируются как таблица. Ручной текст и файлы можно добавить ниже, если сайт плохо парсится.</div>',
        unsafe_allow_html=True,
    )
    competitors: List[CompetitorInput] = []
    current_rows = st.session_state.competitors or [empty_competitor_row()]
    table_df = pd.DataFrame(
        [
            {
                "Компания": row.get("name", ""),
                "URL": row.get("url", ""),
            }
            for row in current_rows
        ]
    )
    edited_df = st.data_editor(
        table_df,
        key="competitor_table",
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "Компания": st.column_config.TextColumn("Компания", width="medium"),
            "URL": st.column_config.TextColumn("URL", width="large"),
        },
    )

    updated_rows: List[Dict[str, str]] = []
    for index, row in edited_df.fillna("").iterrows():
        previous = current_rows[index] if index < len(current_rows) else empty_competitor_row()
        updated_rows.append(
            {
                "name": str(row.get("Компания", "")).strip(),
                "url": str(row.get("URL", "")).strip(),
                "manual_text": previous.get("manual_text", ""),
                "uploaded_text": previous.get("uploaded_text", ""),
            }
        )
    if not updated_rows:
        updated_rows = [empty_competitor_row()]
    st.session_state.competitors = updated_rows

    with st.expander("Резервные источники: ручной текст и файлы", expanded=False):
        for index, row in enumerate(st.session_state.competitors):
            label = row.get("name", "").strip() or row.get("url", "").strip() or f"Строка {index + 1}"
            if not has_filled_competitor_rows([row]) and index > 0:
                continue
            st.markdown(f"**{label}**")
            row["manual_text"] = st.text_area(
                "Ручной текст, если сайт не парсится",
                value=row.get("manual_text", ""),
                height=100,
                key=f"manual_{index}",
            )
            uploaded_files = st.file_uploader(
                "PDF / HTML / DOCX / TXT как резервный источник",
                type=["pdf", "html", "htm", "docx", "txt", "md", "csv"],
                accept_multiple_files=True,
                key=f"files_{index}",
            )
            row["uploaded_text"] = extract_uploaded_text(uploaded_files)

    add_col, clean_col = st.columns(2)
    if add_col.button("Добавить конкурента", use_container_width=True):
        sync_competitor_rows_from_widgets()
        st.session_state.competitors.append({"name": "", "url": "", "manual_text": "", "uploaded_text": ""})
        reset_competitor_widget_state()
        save_draft_state()
        st.rerun()
    if clean_col.button("Удалить пустые строки", use_container_width=True):
        compact_competitor_rows()
        st.rerun()
    for row in st.session_state.competitors:
        if row["name"].strip() or row["url"].strip() or row["manual_text"].strip() or row["uploaded_text"].strip():
            competitors.append(CompetitorInput(**row))
    save_draft_state()
    return competitors


def empty_competitor_row() -> Dict[str, str]:
    return {"name": "", "url": "", "manual_text": "", "uploaded_text": ""}


def reset_competitor_widget_state(max_rows: int = 40) -> None:
    if "competitor_table" in st.session_state:
        del st.session_state["competitor_table"]
    for index in range(max_rows):
        for prefix in ["name", "url", "manual", "files"]:
            key = f"{prefix}_{index}"
            if key in st.session_state:
                del st.session_state[key]


def hydrate_competitor_widget_state() -> None:
    reset_competitor_widget_state(max(40, len(st.session_state.competitors) + 5))
    for index, row in enumerate(st.session_state.competitors):
        st.session_state[f"name_{index}"] = row.get("name", "")
        st.session_state[f"url_{index}"] = row.get("url", "")
        st.session_state[f"manual_{index}"] = row.get("manual_text", "")


def queue_competitor_rows(rows: List[Dict[str, str]]) -> None:
    st.session_state.pending_competitor_rows = rows


def apply_pending_competitor_rows() -> None:
    pending_rows = st.session_state.pop("pending_competitor_rows", None)
    if pending_rows is None:
        return
    st.session_state.competitors = pending_rows
    hydrate_competitor_widget_state()
    save_draft_state()


def sync_selected_preset(selected_preset: str) -> None:
    if selected_preset != st.session_state.active_preset:
        sync_competitor_rows_from_widgets()
        had_competitors = has_filled_competitor_rows(st.session_state.competitors)
        st.session_state.template_groups = (
            preset_groups(selected_preset) if selected_preset != "Свой список" else deepcopy(DEFAULT_TEMPLATE_GROUPS)
        )
        reset_template_widget_state()
        if selected_preset != "Свой список" and not had_competitors:
            st.session_state.competitors = preset_competitors(selected_preset) + [empty_competitor_row()]
            hydrate_competitor_widget_state()
            st.session_state.preset_apply_message = "Компании из пресета добавлены автоматически"
    st.session_state.active_preset = selected_preset
    save_draft_state()


def add_companies_to_editor(companies: List[Dict[str, str]]) -> None:
    sync_competitor_rows_from_widgets()
    current_rows = [
        {
            "name": row.get("name", ""),
            "url": row.get("url", ""),
            "manual_text": row.get("manual_text", ""),
            "uploaded_text": row.get("uploaded_text", ""),
        }
        for row in st.session_state.competitors
        if row.get("name", "").strip() or row.get("url", "").strip() or row.get("manual_text", "").strip() or row.get("uploaded_text", "").strip()
    ]
    existing = {(row.get("name", "").strip().lower(), row.get("url", "").strip().lower()) for row in current_rows}
    added_count = 0
    for company in companies:
        key = (company.get("name", "").strip().lower(), company.get("url", "").strip().lower())
        if key not in existing:
            current_rows.append(
                {
                    "name": company.get("name", ""),
                    "url": company.get("url", ""),
                    "manual_text": company.get("manual_text", ""),
                    "uploaded_text": company.get("uploaded_text", ""),
                }
            )
            existing.add(key)
            added_count += 1
    current_rows.append(empty_competitor_row())
    queue_competitor_rows(current_rows)
    st.session_state.preset_apply_message = f"Добавлено компаний из пресета: {added_count}"
    st.rerun()


def render_preset_company_picker(preset_name: str) -> None:
    if preset_name == "Свой список":
        return
    st.markdown("#### Компании из пресета")
    if st.session_state.get("preset_apply_message"):
        st.success(st.session_state.preset_apply_message)
        st.session_state.preset_apply_message = ""
    preset_rows = preset_competitors(preset_name)
    selected: List[Dict[str, str]] = []
    for index, company in enumerate(preset_rows):
        label = f"{company['name']} — {company['url']}"
        if st.checkbox(label, value=True, key=f"preset_company_{preset_name}_{index}"):
            selected.append(company)
    if st.button("Добавить выбранные компании", use_container_width=True):
        add_companies_to_editor(selected)


def render_preset_cards() -> str:
    st.markdown("#### Пресеты")
    custom_active = st.session_state.active_preset == "Свой список"
    custom_class = "preset-card preset-card-active" if custom_active else "preset-card"
    st.markdown(
        f"""
        <div class="{custom_class}">
            <div class="preset-name">Свой список</div>
            <div class="preset-meta">Ручная настройка компаний и параметров</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Выбрать свой список", use_container_width=True, key="preset_card_custom"):
        st.session_state.preset_selector = "Свой список"
        sync_selected_preset("Свой список")
        st.rerun()

    for name in preset_names():
        groups = preset_groups(name)
        company_count = len(preset_competitors(name))
        parameter_count = sum(len(values) for values in groups.values())
        active = st.session_state.active_preset == name
        card_class = "preset-card preset-card-active" if active else "preset-card"
        short_name = name.split(":", 1)[0]
        st.markdown(
            f"""
            <div class="{card_class}">
                <div class="preset-name">{short_name}</div>
                <div class="preset-meta">{company_count} компаний · {parameter_count} параметров</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Выбрано" if active else "Выбрать", use_container_width=True, key=f"preset_card_{name}"):
            st.session_state.preset_selector = name
            sync_selected_preset(name)
            st.rerun()
    return st.session_state.active_preset


def render_workspace_header(title: str, research_type: str, template: ResearchTemplate, previous_runs_count: int) -> None:
    competitor_count = sum(1 for row in st.session_state.competitors if has_filled_competitor_rows([row]))
    if CONFIG.github_corpus_write_enabled:
        corpus_status = "GitHub corpus: чтение и запись"
    elif CONFIG.github_corpus_read_enabled:
        corpus_status = "GitHub corpus: только чтение"
    else:
        corpus_status = "Локальный corpus"
    safe_title = html.escape(title)
    safe_research_type = html.escape(research_type)
    st.markdown(
        f"""
        <div class="workspace-header">
            <div class="workspace-kicker">AI research workspace</div>
            <div class="workspace-title">{safe_title}</div>
            <div class="workspace-subtitle">Настройте компании и параметры, запустите сбор источников, затем проверьте готовую конкурентную таблицу, выводы и доказательную базу.</div>
            <div class="workspace-meta">
                <span class="meta-pill">{safe_research_type}</span>
                <span class="meta-pill">{competitor_count} компаний</span>
                <span class="meta-pill">{len(template.parameters)} параметров</span>
                <span class="meta-pill">{previous_runs_count} сохранённых запусков</span>
                <span class="meta-pill">{corpus_status}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_exports(run: ResearchRun, diff: List[Dict[str, object]]) -> None:
    st.subheader("Экспорт")
    df = cells_to_dataframe(run.cells)
    evidence_df = cells_to_evidence_dataframe(run.cells)
    col1, col2, col3 = st.columns(3)
    col1.download_button("CSV", export_csv(df), "battle_card.csv", "text/csv", use_container_width=True)
    col2.download_button(
        "Excel",
        export_excel(df, run.insights, run.logs, diff, evidence_df=evidence_df),
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
            "CSV с источниками и статусами",
            export_csv(evidence_df),
            "battle_card_sources.csv",
            "text/csv",
            use_container_width=True,
        )
        st.download_button(
            "JSON исследования",
            json.dumps(run.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"),
            f"{run.run_id}.json",
            "application/json",
        )


init_state()
apply_pending_competitor_rows()

previous_runs = STORAGE.list_runs()

with st.sidebar:
    st.header("Настройка")
    selected_preset = render_preset_cards()
    render_preset_company_picker(selected_preset)
    title = st.text_input("Название исследования", value="Конкурентная таблица")
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
    previous_options = ["Нет"] + [f"{item['run_id']} · {item['title']} · {item['updated_at']}" for item in previous_runs]
    previous_choice = st.selectbox("Сравнить с прошлой версией", previous_options)
    st.divider()
    provider_label = "OpenAI" if CONFIG.openai_api_key else "Yandex" if CONFIG.yandex_api_key else "Эвристический режим без LLM"
    st.caption(f"LLM provider: {provider_label}")

research_type = preset_research_type(st.session_state.active_preset) if st.session_state.active_preset != "Свой список" else "Свой список"

default_template = ResearchTemplate(
    name=st.session_state.active_preset if st.session_state.active_preset != "Свой список" else "Свой шаблон",
    research_type=research_type,
    groups=st.session_state.template_groups,
    detail_level=detail_level,
)

render_workspace_header(title, research_type, default_template, len(previous_runs))

left, right = st.columns([0.38, 0.62], gap="large")

with left:
    template = template_editor(default_template)
    st.session_state.template_groups = template.groups
    save_draft_state()
    competitors = competitor_editor()
    run_button = st.button(
        "Запустить исследование",
        type="primary",
        use_container_width=True,
        disabled=bool(st.session_state.get("is_running")),
    )

with right:
    context_cols = st.columns(3)
    context_cols[0].caption(f"Конкурентов: {len(competitors)}")
    context_cols[1].caption(f"Параметров: {len(template.parameters)}")
    context_cols[2].caption(f"Сохранённых исследований: {len(previous_runs)}")

    status_placeholder = st.empty()
    with status_placeholder.container():
        render_compact_runtime_status()
    with st.expander("Технические логи", expanded=False):
        logs_content_placeholder = st.empty()
        with logs_content_placeholder.container():
            render_live_logs(st.session_state.current_run)

if run_button:
    st.session_state.is_running = True
    sync_competitor_rows_from_widgets()
    competitors = [
        CompetitorInput(**row)
        for row in st.session_state.competitors
        if row.get("name", "").strip()
        or row.get("url", "").strip()
        or row.get("manual_text", "").strip()
        or row.get("uploaded_text", "").strip()
    ]
    st.session_state.run_started_at = time.time()
    st.session_state.current_last_event_at = time.time()
    st.session_state.last_autosave_at = 0.0
    st.session_state.current_progress = 0.0
    st.session_state.current_message = "Запуск исследования"
    previous_data = None
    if previous_choice != "Нет":
        previous_run_id = previous_choice.split(" · ", 1)[0]
        previous_data = STORAGE.load_run(previous_run_id)
    try:
        pipeline = ResearchPipeline(CONFIG, STORAGE, CACHE)
        run = pipeline.run(
            title=title,
            research_type=research_type,
            competitors=competitors,
            template=template,
            detail_level=detail_level,
            rerun_from_stage=None if rerun_from_stage == "Полный запуск" else rerun_from_stage,
            previous_run=previous_data,
            on_event=run_event,
        )
        st.session_state.current_run = run
        st.session_state.current_progress = 1.0
        st.session_state.current_message = f"Готово: исследование сохранено {run.run_id}"
        st.success(f"Исследование сохранено: {run.run_id}")
    except Exception as exc:
        st.session_state.current_message = f"Ошибка: {exc}"
        st.error(f"Исследование остановилось с ошибкой: {exc}")
    finally:
        st.session_state.is_running = False

run = st.session_state.current_run
if run:
    st.divider()
    current_df = cells_to_dataframe(run.cells)
    previous_data = None
    if previous_choice != "Нет":
        previous_run_id = previous_choice.split(" · ", 1)[0]
        previous_data = STORAGE.load_run(previous_run_id)
    diff = diff_runs(previous_data or {}, run.to_dict()) if previous_data else []

    result_tabs = st.tabs(["Таблица", "Выводы", "Источники и доверие", "Версии и экспорт"])
    with result_tabs[0]:
        st.subheader("Сравнительная таблица")
        st.dataframe(current_df, use_container_width=True, hide_index=True)
    with result_tabs[1]:
        render_insights(run.insights)
    with result_tabs[2]:
        edited_cells = render_review_table(run)
        with st.expander("JSON правок", expanded=False):
            st.json(edited_cells, expanded=False)
    with result_tabs[3]:
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
