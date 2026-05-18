from __future__ import annotations

from typing import Dict, List

import pandas as pd
import streamlit as st

from .models import CellStatus, ResearchRun, ResearchTemplate, StageStatus


STATUS_COLORS = {
    "confirmed": "#16794c",
    "ambiguous": "#9a6700",
    "conflicting": "#b42318",
    "missing": "#667085",
    "inferred": "#175cd3",
    "needs_review": "#b54708",
}


STATUS_LABELS = {
    "confirmed": "подтверждено",
    "ambiguous": "неоднозначно",
    "conflicting": "конфликт",
    "missing": "нет данных",
    "inferred": "выведено",
    "needs_review": "нужна проверка",
}

STATUS_VALUES = {label: value for value, label in STATUS_LABELS.items()}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def inject_workspace_css() -> None:
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.4rem; max-width: 1480px;}
        [data-testid="stMetricValue"] {font-size: 1.4rem;}
        .research-shell {border: 1px solid #e4e7ec; border-radius: 8px; padding: 14px 16px; background: #ffffff;}
        .runtime-line {display: flex; align-items: center; justify-content: space-between; gap: 16px; border: 1px solid #e4e7ec; border-radius: 8px; padding: 10px 12px; background: #ffffff; font-size: 14px;}
        .runtime-line strong {font-weight: 650;}
        .runtime-meta {display: flex; gap: 16px; white-space: nowrap; color: #475467;}
        .stage-pill {display: inline-flex; align-items: center; gap: 6px; border: 1px solid #e4e7ec; border-radius: 999px; padding: 4px 10px; margin: 3px; font-size: 12px;}
        .status-dot {width: 8px; height: 8px; border-radius: 50%;}
        .cell-badge {border-radius: 999px; color: white; padding: 2px 8px; font-size: 12px;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_stage_timeline(run: ResearchRun | None) -> None:
    if not run:
        st.info("Pipeline готов к запуску. После старта здесь появятся статусы каждого этапа.")
        return
    html = []
    color_map = {
        StageStatus.PENDING.value: "#d0d5dd",
        StageStatus.RUNNING.value: "#1570ef",
        StageStatus.SUCCESS.value: "#12b76a",
        StageStatus.WARNING.value: "#f79009",
        StageStatus.FAILED.value: "#f04438",
        StageStatus.SKIPPED.value: "#98a2b3",
    }
    for stage in run.stages:
        status = stage.status.value if hasattr(stage.status, "value") else stage.status
        color = color_map.get(status, "#d0d5dd")
        html.append(
            f"<span class='stage-pill'><span class='status-dot' style='background:{color}'></span>{stage.name}</span>"
        )
    st.markdown("".join(html), unsafe_allow_html=True)


def render_live_logs(run: ResearchRun | None, height: int = 240) -> None:
    if not run or not run.logs:
        st.caption("Логи появятся после запуска.")
        return
    lines = [
        f"{item['timestamp']} · {item['level']} · {item.get('stage','')} · {item.get('competitor','')} · {item['message']}"
        for item in run.logs[-120:]
    ]
    st.code("\n".join(lines), language="text", line_numbers=False)


def render_review_table(run: ResearchRun) -> Dict[str, Dict[str, Dict[str, object]]]:
    st.subheader("Проверка данных")
    edited: Dict[str, Dict[str, Dict[str, object]]] = {}
    for competitor, fields in run.cells.items():
        with st.expander(competitor, expanded=True):
            rows = []
            for field, cell in fields.items():
                rows.append(
                    {
                        "Параметр": field,
                        "Извлечено": cell.extracted_value,
                        "Нормализовано": cell.normalized_value,
                        "Статус": status_label(cell.status.value),
                        "Уверенность": cell.confidence_score,
                        "Фрагмент источника": cell.source_fragment,
                        "Обоснование": cell.reasoning,
                    }
                )
            df = pd.DataFrame(rows)
            edited_df = st.data_editor(
                df,
                key=f"review_{run.run_id}_{competitor}",
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Статус": st.column_config.SelectboxColumn("Статус", options=[status_label(status.value) for status in CellStatus]),
                    "Уверенность": st.column_config.NumberColumn("Уверенность", min_value=0.0, max_value=1.0, step=0.05),
                    "Фрагмент источника": st.column_config.TextColumn("Фрагмент источника", width="large"),
                    "Обоснование": st.column_config.TextColumn("Обоснование", width="large"),
                },
            )
            edited[competitor] = {
                row["Параметр"]: {
                    "extracted_value": row["Извлечено"],
                    "normalized_value": row["Нормализовано"],
                    "status": STATUS_VALUES.get(row["Статус"], row["Статус"]),
                    "confidence_score": row["Уверенность"],
                    "source_fragment": row["Фрагмент источника"],
                    "reasoning": row["Обоснование"],
                }
                for _, row in edited_df.iterrows()
            }
    return edited


def render_insights(insights: Dict[str, object]) -> None:
    st.subheader("Выводы по таблице")
    tbank_items = insights.get("tbank_vs_market", [])
    parameter_items = insights.get("parameter_comparison", [])
    if tbank_items:
        tabs = st.tabs(["Т-Банк vs рынок", "Компании по параметрам"])
        with tabs[0]:
            render_list("Сравнение Т-Банка с рынком", tbank_items)
        with tabs[1]:
            render_list("Сравнение компаний между собой по каждому параметру", parameter_items)
    else:
        render_list("Сравнение компаний между собой по каждому параметру", parameter_items)


def render_list(title: str, items: object) -> None:
    st.markdown(f"**{title}**")
    if isinstance(items, list) and items:
        for item in items:
            st.write(f"- {item}")
    elif items:
        st.json(items, expanded=False)
    else:
        st.caption("Нет данных.")


def template_editor(default_template: ResearchTemplate) -> ResearchTemplate:
    st.markdown("#### Конструктор сравнительной таблицы")
    st.caption(
        "Параметры ниже — это целевая схема исследования. Модель будет искать именно эти пункты "
        "в источниках и нормализовать ответы под них. Можно редактировать формулировки, но лучше "
        "оставлять один параметр на строку: например «ПСК», «Срок кредита», «Требования к заёмщику»."
    )
    groups: Dict[str, List[str]] = {}
    for group, values in default_template.groups.items():
        text = st.text_area(group, value="\n".join(values), height=150, key=f"group_{group}")
        groups[group] = [line.strip() for line in text.splitlines() if line.strip()]
    with st.expander("AI suggestions параметров", expanded=False):
        st.write("Добавьте найденные системой параметры после первого запуска: FAQ, тарифы, SLA, ограничения, документы, интеграции.")
    return ResearchTemplate(
        name=default_template.name,
        research_type=default_template.research_type,
        groups=groups,
        detail_level=default_template.detail_level,
    )
