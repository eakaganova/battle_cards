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
    st.subheader("AI-аналитика")
    tabs = st.tabs(["Резюме", "Стратегия", "Продажи и UX", "SWOT", "Неопределённость"])
    with tabs[0]:
        render_list("Краткое резюме", insights.get("executive_summary", []))
        render_list("Продуктовые выводы", insights.get("product_conclusions", []))
    with tabs[1]:
        render_list("Конкурентные преимущества", insights.get("competitive_advantages", []))
        render_list("Пробелы", insights.get("gaps", []))
        render_list("Рекомендации", insights.get("recommendations", []))
        render_list("Позиционирование", insights.get("positioning_analysis", []))
    with tabs[2]:
        render_list("Выводы для продаж", insights.get("sales_insights", []))
        render_list("UX-выводы", insights.get("ux_insights", []))
        render_list("Сравнение ценностных предложений", insights.get("value_proposition_comparison", []))
    with tabs[3]:
        render_swot(insights.get("swot", {}))
    with tabs[4]:
        render_list("Замечания по неопределённости", insights.get("uncertainty_notes", []))
        st.json(insights.get("conflicts", {}), expanded=False)


def render_list(title: str, items: object) -> None:
    st.markdown(f"**{title}**")
    if isinstance(items, list) and items:
        for item in items:
            st.write(f"- {item}")
    elif items:
        st.json(items, expanded=False)
    else:
        st.caption("Нет данных.")


def render_swot(swot: object) -> None:
    if not isinstance(swot, dict) or not swot:
        st.caption("Нет данных.")
        return
    title_map = {
        "strengths": "Сильные стороны",
        "weaknesses": "Слабые стороны",
        "opportunities": "Возможности",
        "threats": "Риски",
    }
    for key, title in title_map.items():
        render_list(title, swot.get(key, []))


def template_editor(default_template: ResearchTemplate) -> ResearchTemplate:
    st.markdown("#### Конструктор сравнительной таблицы")
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
        audience=default_template.audience,
        detail_level=default_template.detail_level,
    )
