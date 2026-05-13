from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from .config import AppConfig
from .models import CellStatus, EvidenceCell


class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, prompt: str) -> Dict[str, Any]:
        raise NotImplementedError


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        default_headers: Dict[str, str] | None = None,
        use_response_format: bool = True,
    ):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url, default_headers=default_headers)
        self.model = model
        self.use_response_format = use_response_format

    def complete_json(self, prompt: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Return valid JSON only. Never fabricate missing facts."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        if self.use_response_format:
            params["response_format"] = {"type": "json_object"}
        response = self.client.chat.completions.create(**params)
        content = response.choices[0].message.content or "{}"
        return parse_json(content)


class HeuristicProvider(LLMProvider):
    """Offline fallback that keeps the product usable when no LLM key is configured."""

    def complete_json(self, prompt: str) -> Dict[str, Any]:
        parameters = extract_prompt_list(prompt, "Параметры:")
        source_text = prompt.split("Текст источника:", 1)[-1] if "Текст источника:" in prompt else prompt
        cells: List[Dict[str, Any]] = []
        for parameter in parameters:
            fragment, score = find_fragment(parameter, source_text)
            status = CellStatus.CONFIRMED.value if fragment else CellStatus.MISSING.value
            cells.append(
                {
                    "raw_field": parameter,
                    "canonical_field": parameter,
                    "extracted_value": fragment[:240] if fragment else "",
                    "normalized_value": fragment[:240] if fragment else "",
                    "source_fragment": fragment[:500] if fragment else "",
                    "confidence_score": score,
                    "status": status,
                    "reasoning": "Найдено эвристическим поиском по тексту." if fragment else "Не найдено в доступном тексте.",
                    "extraction_method": "heuristic_offline_extraction",
                }
            )
        return {
            "cells": cells,
            "suggested_new_parameters": suggest_parameters(source_text),
            "executive_summary": ["LLM не настроена, поэтому создан эвристический анализ с явной низкой уверенностью."],
        }


def provider_from_config(config: AppConfig) -> LLMProvider:
    if config.llm_provider in {"openai", "auto"} and config.openai_api_key:
        return OpenAICompatibleProvider(config.openai_api_key, config.openai_model)
    if config.llm_provider in {"yandex", "auto"} and config.yandex_api_key and config.yandex_folder:
        return OpenAICompatibleProvider(
            api_key=config.yandex_api_key,
            model=yandex_model_uri(config.yandex_folder, config.yandex_model),
            base_url=config.yandex_base_url,
            default_headers={"x-folder-id": config.yandex_folder},
            use_response_format=False,
        )
    return HeuristicProvider()


def yandex_model_uri(folder_id: str, model: str) -> str:
    model = (model or "").strip()
    if model.startswith("gpt://"):
        return model
    return f"gpt://{folder_id}/{model or 'yandexgpt/latest'}"


def parse_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group(0))
    return {}


def cells_from_llm_payload(payload: Dict[str, Any], source_url: str) -> List[EvidenceCell]:
    result: List[EvidenceCell] = []
    for item in payload.get("cells", []):
        status = item.get("status") or CellStatus.NEEDS_REVIEW.value
        if status not in CellStatus._value2member_map_:
            status = CellStatus.NEEDS_REVIEW.value
        result.append(
            EvidenceCell(
                extracted_value=str(item.get("extracted_value", "") or ""),
                normalized_value=str(item.get("normalized_value", "") or item.get("extracted_value", "") or ""),
                canonical_field=str(item.get("canonical_field", "") or item.get("raw_field", "") or ""),
                source_url=str(item.get("source_url", "") or source_url),
                source_fragment=str(item.get("source_fragment", "") or ""),
                confidence_score=float(item.get("confidence_score", 0.0) or 0.0),
                extraction_method=str(item.get("extraction_method", "llm_structured_extraction")),
                status=CellStatus(status),
                reasoning=str(item.get("reasoning", "") or ""),
                raw_field=str(item.get("raw_field", "") or ""),
            )
        )
    return result


def extract_prompt_list(prompt: str, marker: str) -> List[str]:
    if marker not in prompt:
        return []
    block = prompt.split(marker, 1)[1].split("\n\n", 1)[0]
    return [line.strip("- ").strip() for line in block.splitlines() if line.strip().startswith("-")]


def find_fragment(parameter: str, text: str) -> tuple[str, float]:
    keywords = [word.lower() for word in re.findall(r"[A-Za-zА-Яа-я0-9]{4,}", parameter)]
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    best = ""
    best_score = 0.0
    for sentence in sentences:
        lowered = sentence.lower()
        hits = sum(1 for word in keywords if word in lowered)
        if keywords and hits / len(keywords) > best_score:
            best = sentence.strip()
            best_score = hits / len(keywords)
    if best_score < 0.34:
        return "", 0.0
    return best, round(min(best_score, 0.68), 2)


def suggest_parameters(text: str) -> List[str]:
    candidates = []
    for label in ["FAQ", "Интеграции", "Безопасность", "Тарифы", "Документы", "Ограничения"]:
        if label.lower() in text.lower():
            candidates.append(label)
    return candidates[:6]
