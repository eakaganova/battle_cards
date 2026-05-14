from __future__ import annotations

from typing import Iterable, List


EXTRACTION_PROMPT_VERSION = "extraction.v3.ru-evidence"
ANALYTICS_PROMPT_VERSION = "analytics.v4.strict-comparison-formats"


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


def build_analytics_prompt(
    title: str,
    research_type: str,
    table_json: str,
    detail_level: str,
    has_tbank: bool,
) -> str:
    return f"""
Ты аналитик конкурентных карт для русскоязычной аудитории.
Сгенерируй выводы строго в двух разрешённых форматах. Никаких SWOT, summary, recommendations, sales insights, UX insights и общих рассуждений.

Разрешённые форматы:
1. tbank_vs_market: только если has_tbank=true. Каждый пункт обязан начинаться одной из фраз:
   - "Т-Банк лучше конкурентов ..."
   - "Т-Банк наравне с конкурентами ..."
   - "Т-Банк хуже конкурентов ..."
   Если has_tbank=false, верни пустой список tbank_vs_market=[].
2. parameter_comparison: сравнение компаний между собой по каждому параметру.
   Формат каждого пункта: "По <параметр> лучшие условия предлагает <компания>, а худшие — <компания>."
   Если лучшего/худшего нельзя определить из-за отсутствия или неоднозначности данных, явно напиши:
   "По <параметр> невозможно надёжно определить лучшие и худшие условия: <причина>."

Правила:
- Используй только данные из table_json.
- Не придумывай значения.
- Если данные отсутствуют, так и пиши.
- Все тексты должны быть на русском.
- Не добавляй другие разделы и другие ключи JSON.

Верни только JSON:
{{
  "tbank_vs_market": ["..."],
  "parameter_comparison": ["..."]
}}

title={title}
research_type={research_type}
detail_level={detail_level}
has_tbank={str(has_tbank).lower()}
prompt_version={ANALYTICS_PROMPT_VERSION}

Battle-card JSON:
{table_json}
""".strip()
