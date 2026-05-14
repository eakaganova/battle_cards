from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CellStatus(str, Enum):
    CONFIRMED = "confirmed"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"
    MISSING = "missing"
    INFERRED = "inferred"
    NEEDS_REVIEW = "needs_review"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


PIPELINE_STAGE_NAMES = [
    "Получение URL",
    "Парсинг",
    "Раскрытие аккордеонов/кнопок",
    "Загрузка динамического контента",
    "Извлечение текста",
    "Очистка текста",
    "Chunking",
    "LLM extraction",
    "Нормализация",
    "Schema alignment",
    "Построение таблицы",
    "Проверка конфликтов",
    "Генерация выводов",
    "Экспорт",
]


@dataclass
class CompetitorInput:
    name: str
    url: str = ""
    manual_text: str = ""
    uploaded_text: str = ""

    def display_name(self) -> str:
        return self.name.strip() or self.url.strip() or "Без названия"


@dataclass
class ResearchTemplate:
    name: str
    research_type: str
    groups: Dict[str, List[str]]
    detail_level: str = "Balanced"

    @property
    def parameters(self) -> List[str]:
        result: List[str] = []
        for values in self.groups.values():
            for value in values:
                if value not in result:
                    result.append(value)
        return result


@dataclass
class SourceArtifact:
    competitor: str
    url: str
    raw_html: str = ""
    raw_text: str = ""
    cleaned_text: str = ""
    tables: List[Dict[str, Any]] = field(default_factory=list)
    faq_items: List[Dict[str, str]] = field(default_factory=list)
    pdf_links: List[str] = field(default_factory=list)
    iframe_urls: List[str] = field(default_factory=list)
    modal_texts: List[str] = field(default_factory=list)
    hidden_text: str = ""
    extraction_method: str = "unknown"
    status: str = "pending"
    errors: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass
class EvidenceCell:
    extracted_value: str = ""
    normalized_value: str = ""
    canonical_field: str = ""
    source_url: str = ""
    source_fragment: str = ""
    confidence_score: float = 0.0
    extraction_method: str = "unknown"
    timestamp: str = field(default_factory=utc_now_iso)
    status: CellStatus = CellStatus.MISSING
    reasoning: str = ""
    raw_field: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value if isinstance(self.status, CellStatus) else self.status
        return data


@dataclass
class PipelineStage:
    name: str
    status: StageStatus = StageStatus.PENDING
    message: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def start(self, message: str = "") -> None:
        self.status = StageStatus.RUNNING
        self.message = message
        self.started_at = utc_now_iso()

    def finish(self, status: StageStatus = StageStatus.SUCCESS, message: str = "", **metrics: Any) -> None:
        self.status = status
        self.message = message
        self.finished_at = utc_now_iso()
        self.metrics.update(metrics)

    def fail(self, error: str) -> None:
        self.status = StageStatus.FAILED
        self.errors.append(error)
        self.message = error
        self.finished_at = utc_now_iso()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value if isinstance(self.status, StageStatus) else self.status
        return data


@dataclass
class ResearchRun:
    run_id: str
    title: str
    research_type: str
    competitors: List[CompetitorInput]
    template: ResearchTemplate
    stages: List[PipelineStage] = field(default_factory=lambda: [PipelineStage(name) for name in PIPELINE_STAGE_NAMES])
    artifacts: List[SourceArtifact] = field(default_factory=list)
    cells: Dict[str, Dict[str, EvidenceCell]] = field(default_factory=dict)
    insights: Dict[str, Any] = field(default_factory=dict)
    logs: List[Dict[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def log(self, level: str, message: str, stage: str = "", competitor: str = "") -> None:
        self.logs.append(
            {
                "timestamp": utc_now_iso(),
                "level": level,
                "stage": stage,
                "competitor": competitor,
                "message": message,
            }
        )
        self.updated_at = utc_now_iso()

    def stage(self, name: str) -> PipelineStage:
        for stage in self.stages:
            if stage.name == name:
                return stage
        new_stage = PipelineStage(name)
        self.stages.append(new_stage)
        return new_stage

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "title": self.title,
            "research_type": self.research_type,
            "competitors": [asdict(item) for item in self.competitors],
            "template": asdict(self.template),
            "stages": [stage.to_dict() for stage in self.stages],
            "artifacts": [asdict(item) for item in self.artifacts],
            "cells": {
                competitor: {field_name: cell.to_dict() for field_name, cell in fields.items()}
                for competitor, fields in self.cells.items()
            },
            "insights": self.insights,
            "logs": self.logs,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


DEFAULT_TEMPLATE_GROUPS = {
    "Цена и условия": [
        "Стоимость / тариф",
        "Процентная ставка",
        "ПСК",
        "Максимальная сумма",
        "Минимальная сумма",
        "Срок",
    ],
    "Продукт": [
        "Основное предложение",
        "Функциональность",
        "Ограничения",
        "Преимущества",
        "Что не указано на странице",
    ],
    "Клиентский путь": [
        "Требования к клиенту",
        "Документы",
        "Как оформить",
        "Поддержка",
        "UX observations",
    ],
    "Риски и доверие": [
        "Комиссии",
        "Страхование",
        "Юридические условия",
        "SLA / гарантии",
    ],
}


RESEARCH_TYPES = [
    "Ипотека",
    "КНЗ",
    "КНА",
    "ОСАГО",
    "SaaS",
    "Fintech",
    "Страхование",
    "B2B platform",
    "E-commerce",
    "Custom",
]
