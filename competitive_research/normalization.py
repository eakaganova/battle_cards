from __future__ import annotations

import re
from difflib import get_close_matches
from typing import Dict, Iterable, List, Tuple

from .models import CellStatus, EvidenceCell


STATUS_ORDER = {
    CellStatus.CONFIRMED.value: 0,
    CellStatus.INFERRED.value: 1,
    CellStatus.AMBIGUOUS.value: 2,
    CellStatus.NEEDS_REVIEW.value: 3,
    CellStatus.CONFLICTING.value: 4,
    CellStatus.MISSING.value: 5,
}


def normalize_value(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    text = re.sub(r"(\d+)\s*месяц(?:ев|а)?", lambda m: months_to_years(m.group(1)), text, flags=re.I)
    text = re.sub(r"360\s*мес\w*", "30 лет", text, flags=re.I)
    text = re.sub(r"до\s+30\s+лет", "30 лет", text, flags=re.I)
    text = re.sub(r"максимальн\w*\s+срок\s*[—-]?\s*30\s+лет", "30 лет", text, flags=re.I)
    text = re.sub(r"\s+%", "%", text)
    return text


def months_to_years(months_text: str) -> str:
    try:
        months = int(months_text)
    except ValueError:
        return months_text
    if months % 12 == 0:
        years = months // 12
        if years == 1:
            return "1 год"
        if 2 <= years <= 4:
            return f"{years} года"
        return f"{years} лет"
    return f"{months} месяцев"


def canonicalize_field(raw_field: str, canonical_fields: Iterable[str]) -> Tuple[str, float]:
    fields = list(canonical_fields)
    if raw_field in fields:
        return raw_field, 1.0
    matches = get_close_matches(raw_field, fields, n=1, cutoff=0.58)
    if matches:
        return matches[0], 0.78
    lowered = raw_field.lower()
    for field in fields:
        if lowered in field.lower() or field.lower() in lowered:
            return field, 0.72
    return raw_field, 0.45


def align_cells_to_schema(
    raw_cells: List[EvidenceCell],
    canonical_fields: List[str],
    source_url: str,
    extraction_method: str,
) -> Dict[str, EvidenceCell]:
    result: Dict[str, EvidenceCell] = {}
    for field in canonical_fields:
        result[field] = EvidenceCell(
            canonical_field=field,
            source_url=source_url,
            extraction_method=extraction_method,
            status=CellStatus.MISSING,
            reasoning="Параметр не найден в источнике.",
        )

    for cell in raw_cells:
        canonical, mapping_confidence = canonicalize_field(cell.canonical_field or cell.raw_field, canonical_fields)
        if canonical not in result:
            canonical = cell.canonical_field or cell.raw_field
        cell.canonical_field = canonical
        cell.normalized_value = normalize_value(cell.normalized_value or cell.extracted_value)
        cell.confidence_score = round(min(float(cell.confidence_score or 0.0), mapping_confidence), 2)
        existing = result.get(canonical)
        if existing and existing.status != CellStatus.MISSING and existing.extracted_value != cell.extracted_value:
            existing.status = CellStatus.CONFLICTING
            existing.reasoning = f"Найдено несколько разных значений: {existing.extracted_value}; {cell.extracted_value}"
            existing.confidence_score = min(existing.confidence_score, cell.confidence_score, 0.55)
            continue
        result[canonical] = cell
    return result


def detect_conflicts(cells_by_competitor: Dict[str, Dict[str, EvidenceCell]]) -> Dict[str, List[str]]:
    conflicts: Dict[str, List[str]] = {}
    for competitor, cells in cells_by_competitor.items():
        for field, cell in cells.items():
            if cell.status in {CellStatus.CONFLICTING, CellStatus.AMBIGUOUS, CellStatus.NEEDS_REVIEW}:
                conflicts.setdefault(competitor, []).append(field)
            elif cell.confidence_score < 0.55 and cell.status != CellStatus.MISSING:
                cell.status = CellStatus.NEEDS_REVIEW
                conflicts.setdefault(competitor, []).append(field)
    return conflicts
