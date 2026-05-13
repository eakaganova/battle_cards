from __future__ import annotations

from typing import Iterable, List


EXTRACTION_PROMPT_VERSION = "extraction.v3.ru-evidence"
ANALYTICS_PROMPT_VERSION = "analytics.v3.ru-board-ready"


def build_extraction_prompt(
    competitor: str,
    source_url: str,
    research_type: str,
    parameters: Iterable[str],
    source_text: str,
) -> str:
    params = "\n".join(f"- {item}" for item in parameters)
    return f"""
Ты извлекаешь факты для русскоязычного сервиса конкурентного анализа.
Пиши все пользовательские значения на русском языке: normalized_value, canonical_field, reasoning и suggested_new_parameters.
Если источник на английском или другом языке, extracted_value может сохранить исходную формулировку, но normalized_value обязательно переведи и нормализуй по-русски.
source_fragment оставляй как в источнике, без перевода, чтобы пользователь мог проверить доказательство.

Запрещено выдумывать данные.
Если параметр отсутствует, верни status="missing", пустое значение и объясни причину по-русски.
Если данные спорные или есть несколько значений, верни status="ambiguous" или "conflicting".

Верни только JSON без markdown. Схема:
{{
  "competitor": "...",
  "source_url": "...",
  "cells": [
    {{
      "raw_field": "название параметра из списка",
      "canonical_field": "каноническое название на русском",
      "extracted_value": "как написано в источнике",
      "normalized_value": "единый формат на русском языке",
      "source_fragment": "короткий фрагмент из источника",
      "confidence_score": 0.0,
      "status": "confirmed|ambiguous|conflicting|missing|inferred|needs_review",
      "reasoning": "краткое объяснение на русском",
      "extraction_method": "llm_structured_extraction"
    }}
  ],
  "suggested_new_parameters": ["параметр на русском"]
}}

Правила:
- confidence_score от 0 до 1.
- source_fragment должен быть взят из текста ниже, не длиннее 500 символов.
- Не нормализуй агрессивно: если смысл неочевиден, оставь status="needs_review".
- Для чисел, сроков, процентов и валют сохраняй extracted_value как в источнике, а normalized_value приводи к русскому единому формату.
- Не используй английские аналитические формулировки в normalized_value и reasoning.

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
Сопоставь сырые поля с канонической русскоязычной схемой.
Не придумывай поля без причины.
Все reasoning и новые параметры пиши по-русски.
Верни JSON:
{{"mapping": [{{"raw_field": "...", "canonical_field": "...", "confidence_score": 0.0, "reasoning": "..."}}], "new_parameters": ["..."]}}

Канонические параметры:
{parameters}

Сырые поля:
{extracted_fields}
""".strip()


def build_analytics_prompt(title: str, research_type: str, table_json: str, audience: str, detail_level: str) -> str:
    return f"""
Ты senior product strategist для русскоязычной аудитории.
Сгенерируй выводы конкурентного анализа на русском языке на основе JSON battle-card.
Не скрывай неопределённость: отдельно укажи, какие выводы зависят от ячеек с низкой уверенностью.
Не используй английские фразы вроде "executive summary", "gaps", "sales insights" внутри текста выводов.
Ключи JSON оставь как в схеме ниже, но все значения внутри массивов и объектов должны быть на русском языке.

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
