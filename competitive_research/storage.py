from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from .config import AppConfig
from .models import CompetitorInput, EvidenceCell, PipelineStage, ResearchRun, ResearchTemplate, SourceArtifact


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


class ResearchStorage:
    def __init__(self, config: AppConfig):
        self.config = config
        self.config.runs_dir.mkdir(parents=True, exist_ok=True)
        self.config.templates_dir.mkdir(parents=True, exist_ok=True)

    def save_run(self, run: ResearchRun) -> Path:
        path = self.config.runs_dir / f"{run.run_id}.json"
        path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def list_runs(self) -> List[Dict[str, str]]:
        result: List[Dict[str, str]] = []
        for path in sorted(self.config.runs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                result.append(
                    {
                        "run_id": data.get("run_id", path.stem),
                        "title": data.get("title", path.stem),
                        "research_type": data.get("research_type", ""),
                        "updated_at": data.get("updated_at", ""),
                    }
                )
            except Exception:
                continue
        return result

    def load_run(self, run_id: str) -> Optional[Dict[str, object]]:
        path = self.config.runs_dir / f"{run_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_template(self, template: ResearchTemplate) -> Path:
        path = self.config.templates_dir / f"{safe_filename(template.name)}.json"
        path.write_text(json.dumps(asdict(template), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def list_templates(self) -> List[ResearchTemplate]:
        templates: List[ResearchTemplate] = []
        for path in self.config.templates_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                templates.append(ResearchTemplate(**data))
            except Exception:
                continue
        return templates


def safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)[:80] or "template"


def diff_runs(previous: Dict[str, object], current: Dict[str, object]) -> List[Dict[str, object]]:
    previous_cells = previous.get("cells", {}) if previous else {}
    current_cells = current.get("cells", {}) if current else {}
    changes: List[Dict[str, object]] = []
    competitors = sorted(set(previous_cells.keys()) | set(current_cells.keys()))
    for competitor in competitors:
        old_fields = previous_cells.get(competitor, {})
        new_fields = current_cells.get(competitor, {})
        for field in sorted(set(old_fields.keys()) | set(new_fields.keys())):
            old_value = (old_fields.get(field) or {}).get("normalized_value", "")
            new_value = (new_fields.get(field) or {}).get("normalized_value", "")
            if old_value != new_value:
                changes.append(
                    {
                        "competitor": competitor,
                        "field": field,
                        "old_value": old_value,
                        "new_value": new_value,
                        "change_type": classify_change(old_value, new_value),
                        "critical": is_critical_change(field, old_value, new_value),
                    }
                )
    return changes


def classify_change(old_value: str, new_value: str) -> str:
    if not old_value and new_value:
        return "added"
    if old_value and not new_value:
        return "removed"
    return "changed"


def is_critical_change(field: str, old_value: str, new_value: str) -> bool:
    field_lower = field.lower()
    return any(token in field_lower for token in ["цена", "ставка", "срок", "сумма", "тариф", "комис", "sla"]) and old_value != new_value
