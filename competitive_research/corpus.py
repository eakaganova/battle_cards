from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from .config import AppConfig
from .models import CellStatus, EvidenceCell, SourceArtifact, utc_now_iso
from .parser import artifact_to_cache_value


class ResearchCorpus:
    def __init__(self, config: AppConfig):
        self.config = config
        self.root = config.corpus_dir
        self.sources_dir = self.root / "sources"
        self.extractions_dir = self.root / "extractions"
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.extractions_dir.mkdir(parents=True, exist_ok=True)

    def load_source(self, competitor: str, url: str) -> Optional[SourceArtifact]:
        key = source_key(competitor, url)
        payload = self._load_json("sources", key)
        if not payload:
            return None
        artifact_data = payload.get("artifact") or payload
        try:
            return SourceArtifact(**artifact_data)
        except Exception:
            return None

    def save_source(self, artifact: SourceArtifact, run_id: str, research_type: str) -> None:
        if not artifact.url.strip() or artifact.status == "failed":
            return
        key = source_key(artifact.competitor, artifact.url)
        payload = {
            "kind": "source_artifact",
            "schema_version": "source.v1",
            "artifact_key": key,
            "run_id": run_id,
            "research_type": research_type,
            "saved_at": utc_now_iso(),
            "competitor": artifact.competitor,
            "url": artifact.url,
            "status": artifact.status,
            "extraction_method": artifact.extraction_method,
            "text_hash": stable_hash(artifact.cleaned_text or artifact.raw_text),
            "artifact": artifact_to_cache_value(artifact),
        }
        self._save_json("sources", key, payload)

    def load_extraction(
        self,
        competitor: str,
        url: str,
        parameters: Iterable[str],
        prompt_version: str,
    ) -> Optional[List[EvidenceCell]]:
        key = extraction_key(competitor, url, parameters, prompt_version)
        payload = self._load_json("extractions", key)
        if not payload:
            return None
        cells = payload.get("cells", [])
        result: List[EvidenceCell] = []
        for item in cells:
            try:
                data = dict(item)
                status = data.get("status") or CellStatus.NEEDS_REVIEW.value
                if status not in CellStatus._value2member_map_:
                    status = CellStatus.NEEDS_REVIEW.value
                data["status"] = CellStatus(status)
                result.append(EvidenceCell(**data))
            except Exception:
                continue
        return result or None

    def save_extraction(
        self,
        competitor: str,
        url: str,
        parameters: Iterable[str],
        prompt_version: str,
        cells: List[EvidenceCell],
        run_id: str,
        research_type: str,
    ) -> None:
        if not url.strip() or not cells:
            return
        key = extraction_key(competitor, url, parameters, prompt_version)
        payload = {
            "kind": "llm_extraction",
            "schema_version": "extraction.v1",
            "artifact_key": key,
            "source_key": source_key(competitor, url),
            "run_id": run_id,
            "research_type": research_type,
            "prompt_version": prompt_version,
            "saved_at": utc_now_iso(),
            "competitor": competitor,
            "url": url,
            "parameters": list(parameters),
            "cells": [cell.to_dict() for cell in cells],
        }
        self._save_json("extractions", key, payload)

    def _load_json(self, namespace: str, key: str) -> Optional[Dict[str, Any]]:
        local_path = self._local_path(namespace, key)
        if local_path.exists():
            try:
                return json.loads(local_path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return self._load_from_github(namespace, key)

    def _save_json(self, namespace: str, key: str, payload: Dict[str, Any]) -> None:
        local_path = self._local_path(namespace, key)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._save_to_github(namespace, key, payload)

    def _local_path(self, namespace: str, key: str) -> Path:
        return self.root / namespace / f"{key}.json"

    def _github_file_path(self, namespace: str, key: str) -> str:
        prefix = self.config.github_corpus_path.strip("/ ")
        return f"{prefix}/{namespace}/{key}.json" if prefix else f"{namespace}/{key}.json"

    def _github_ready(self) -> bool:
        return bool(
            self.config.github_corpus_enabled
            and self.config.github_token
            and self.config.github_repo
        )

    def _load_from_github(self, namespace: str, key: str) -> Optional[Dict[str, Any]]:
        if not self._github_ready():
            return None
        path = self._github_file_path(namespace, key)
        url = f"https://api.github.com/repos/{self.config.github_repo}/contents/{path}"
        try:
            response = requests.get(
                url,
                params={"ref": self.config.github_branch},
                headers=self._github_headers(),
                timeout=20,
            )
            if response.status_code != 200:
                return None
            content = response.json().get("content", "")
            decoded = base64.b64decode(content).decode("utf-8")
            return json.loads(decoded)
        except Exception:
            return None

    def _save_to_github(self, namespace: str, key: str, payload: Dict[str, Any]) -> None:
        if not self._github_ready():
            return
        path = self._github_file_path(namespace, key)
        url = f"https://api.github.com/repos/{self.config.github_repo}/contents/{path}"
        content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        body: Dict[str, Any] = {
            "message": f"Update research corpus {namespace}/{key}",
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.config.github_branch,
        }
        try:
            current = requests.get(
                url,
                params={"ref": self.config.github_branch},
                headers=self._github_headers(),
                timeout=20,
            )
            if current.status_code == 200:
                body["sha"] = current.json().get("sha")
            requests.put(url, headers=self._github_headers(), json=body, timeout=30)
        except Exception:
            return

    def _github_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }


def source_key(competitor: str, url: str) -> str:
    return stable_hash(f"source|{normalize_key_part(competitor)}|{normalize_key_part(url)}")


def extraction_key(competitor: str, url: str, parameters: Iterable[str], prompt_version: str) -> str:
    params = "|".join(normalize_key_part(item) for item in parameters)
    return stable_hash(
        f"extraction|{normalize_key_part(competitor)}|{normalize_key_part(url)}|{prompt_version}|{params}"
    )


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def normalize_key_part(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())
