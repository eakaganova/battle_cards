from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional


class JsonCache:
    def __init__(self, root: Path, ttl_seconds: int = 86400):
        self.root = root
        self.ttl_seconds = ttl_seconds
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        directory = self.root / namespace
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{digest}.json"

    def get(self, namespace: str, key: str) -> Optional[Any]:
        path = self._path(namespace, key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - payload.get("created_at", 0) > self.ttl_seconds:
                return None
            return payload.get("value")
        except Exception:
            return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        path = self._path(namespace, key)
        path.write_text(
            json.dumps({"created_at": time.time(), "value": value}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
