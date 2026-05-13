from __future__ import annotations

from typing import Iterable, List


EXTRACTION_PROMPT_VERSION = "extraction.v2.strict-evidence"
ANALYTICS_PROMPT_VERSION = "analytics.v2.board-ready"


def build_extraction_prompt(
    competitor: str,
    source_url: str,
    research_type: str,
    parameters: Iterable[str],
    source_text: str,
) -> str:
    params = "\n".join(f"- {item}" for item in parameters)
    return f"""
Ты извлекаешь факты для конкурентного анализа. Запрещено выдумывать данные.
Если параметр отсутствует, верни status="missing", пустое значение и объясни причину.
Если данные спорные или есть несколько значений, верни status="ambiguous" или "conflicting".

Верни только JSON без markdown. Схема:
{{
  "competitor": "...",
  "source_url": "...",
  "cells": [
    {{
      "raw_field": "название параметра из списка",
      "canonical_field": "каноническое название",
      "extracted_value": "как написано в источнике",
      "normalized_value": "единый формат, если возможно",
      "source_fragment": "короткая цитата/фрагмент из источника",
      "confidence_score": 0.0,
      "status": "confirmed|ambiguous|conflicting|missing|inferred|needs_review",
      "reasoning": "кратко почему такой статус",
      "extraction_method": "llm_structured_extraction"
    }}
  ],
  "suggested_new_parameters": ["..."]
}}

Правила:
- confidence_score от 0 до 1.
- source_fragment должен быть взят из текста ниже, не длиннее 500 символов.
- Не нормализуй агрессивно: если смысл неочевиден, оставь status="needs_review".
- Для чисел, сроков, процентов и валют сохраняй исходное значение и нормализованное значение.

Контекст:
competitor={competitor}
source_url={source_url}
research_type={research_type}
prompt_version={EXTRACTION_PROMPT_VERSION}

Параметры:
{params}

Текст источника:
{source_text}
""".strip()


def build_schema_alignment_prompt(parameters: List[str], extracted_fields: List[str]) -> str:
    return f"""
Сопоставь сырые поля с канонической схемой. Не придумывай поля без причины.
Верни JSON:
{{"mapping": [{{"raw_field": "...", "canonical_field": "...", "confidence_score": 0.0, "reasoning": "..."}}], "new_parameters": ["..."]}}

Канонические параметры:
{parameters}

Сырые поля:
{extracted_fields}
""".strip()


def build_analytics_prompt(title: str, research_type: str, table_json: str, audience: str, detail_level: str) -> str:
    return f"""
Ты senior product strategist. Сгенерируй выводы конкурентного анализа на основе JSON battle-card.
Не скрывай неопределённость: отдельно укажи, какие выводы зависят от ячеек с низкой уверенностью.
Верни только JSON:
{{
  "executive_summary": ["..."],
  "strengths_weaknesses": {{"competitor": {{"strengths": ["..."], "weaknesses": ["..."]}}}},
  "competitive_advantages": ["..."],
  "gaps": ["..."],
  "recommendations": ["..."],
  "sales_insights": ["..."],
  "ux_insights": ["..."],
  "product_conclusions": ["..."],
  "swot": {{"strengths": ["..."], "weaknesses": ["..."], "opportunities": ["..."], "threats": ["..."]}},
  "positioning_analysis": ["..."],
  "value_proposition_comparison": ["..."],
  "uncertainty_notes": ["..."]
}}

title={title}
research_type={research_type}
audience={audience}
detail_level={detail_level}
prompt_version={ANALYTICS_PROMPT_VERSION}

Battle-card JSON:
{table_json}
""".strip()
