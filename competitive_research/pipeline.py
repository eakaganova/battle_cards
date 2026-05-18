from __future__ import annotations

import json
from typing import Callable, Dict, List, Optional

from .cache import JsonCache
from .config import AppConfig
from .llm import HeuristicProvider, cells_from_llm_payload, provider_from_config
from .models import CompetitorInput, EvidenceCell, ResearchRun, ResearchTemplate, SourceArtifact, StageStatus
from .normalization import align_cells_to_schema, detect_conflicts
from .parser import artifact_to_cache_value, chunk_text, fetch_source, prepare_text_for_llm, select_focused_chunks
from .prompts import EXTRACTION_PROMPT_VERSION, build_analytics_prompt, build_extraction_prompt
from .storage import ResearchStorage, new_run_id


UIEvent = Callable[[ResearchRun, str, str, float], None]


class ResearchPipeline:
    def __init__(self, config: AppConfig, storage: ResearchStorage, cache: JsonCache):
        self.config = config
        self.storage = storage
        self.cache = cache
        self.llm = provider_from_config(config)
        self.fallback_llm = HeuristicProvider()

    def run(
        self,
        title: str,
        research_type: str,
        competitors: List[CompetitorInput],
        template: ResearchTemplate,
        detail_level: str,
        rerun_from_stage: Optional[str] = None,
        previous_run: Optional[Dict[str, object]] = None,
        on_event: Optional[UIEvent] = None,
    ) -> ResearchRun:
        run = ResearchRun(
            run_id=new_run_id(),
            title=title,
            research_type=research_type,
            competitors=competitors,
            template=template,
        )

        self._stage(run, "Получение URL", "Проверяю входные данные.", on_event, 0.03)
        valid_competitors = [item for item in competitors if item.url.strip() or item.manual_text.strip() or item.uploaded_text.strip()]
        if not valid_competitors:
            run.stage("Получение URL").fail("Нужен хотя бы один URL или ручной источник.")
            return run
        run.stage("Получение URL").finish(StageStatus.SUCCESS, competitors=len(valid_competitors))

        artifacts = []
        self._stage(run, "Парсинг", "Начинаю сбор страниц и резервных источников.", on_event, 0.08)
        for index, competitor in enumerate(valid_competitors, start=1):
            run.log("INFO", "Сбор источника начат.", "Парсинг", competitor.display_name())
            source_cache_key = self._source_cache_key(competitor)
            cached_artifact = self.cache.get("source_artifacts", source_cache_key) if source_cache_key else None
            if cached_artifact:
                artifact = SourceArtifact(**cached_artifact)
                run.log("INFO", "Использую сохранённый источник из кэша.", "Парсинг", competitor.display_name())
            else:
                try:
                    artifact = fetch_source(
                        competitor=competitor.display_name(),
                        url=competitor.url,
                        manual_text=competitor.manual_text,
                        uploaded_text=competitor.uploaded_text,
                        config=self.config,
                        progress=lambda stage, name, message: self._progress_log(run, on_event, stage, name, message, 0.08 + index / max(len(valid_competitors), 1) * 0.20),
                    )
                    if source_cache_key and artifact.status != "failed":
                        self.cache.set("source_artifacts", source_cache_key, artifact_to_cache_value(artifact))
                except Exception as exc:
                    artifact = SourceArtifact(
                        competitor=competitor.display_name(),
                        url=competitor.url,
                        status="failed",
                        errors=[str(exc)],
                        extraction_method="parser_failed",
                    )
                    run.log(
                        "ERROR",
                        f"Источник не удалось собрать, продолжаю исследование без него: {exc}",
                        "Парсинг",
                        competitor.display_name(),
                    )
            artifacts.append(artifact)
            if artifact.errors:
                run.log("ERROR", "; ".join(artifact.errors), "Парсинг", competitor.display_name())
        run.artifacts = artifacts
        parse_status = StageStatus.WARNING if any(item.errors or item.status == "failed" for item in artifacts) else StageStatus.SUCCESS
        run.stage("Парсинг").finish(parse_status, "Источники собраны.", artifacts=len(artifacts))

        self._finish_simple_stage(run, "Раскрытие аккордеонов/кнопок", on_event, 0.28, expanded=sum("expanded" in item.status for item in artifacts))
        self._finish_simple_stage(run, "Загрузка динамического контента", on_event, 0.32, dynamic=sum(item.extraction_method.startswith("playwright") for item in artifacts))
        self._finish_simple_stage(run, "Извлечение текста", on_event, 0.36, chars=sum(len(item.raw_text) for item in artifacts))

        self._stage(run, "Очистка текста", "Очищаю текст и ограничиваю объём контекста.", on_event, 0.40)
        for artifact in run.artifacts:
            before_chars = len(artifact.cleaned_text)
            artifact.cleaned_text = prepare_text_for_llm(artifact.cleaned_text)[: self.config.max_source_chars]
            after_chars = len(artifact.cleaned_text)
            run.log(
                "INFO",
                f"Предварительная очистка источника: {before_chars} -> {after_chars} символов.",
                "Очистка текста",
                artifact.competitor,
            )
        run.stage("Очистка текста").finish(StageStatus.SUCCESS, chars=sum(len(item.cleaned_text) for item in artifacts))

        self._stage(run, "Chunking", "Разбиваю источники на chunks для контролируемой LLM-обработки.", on_event, 0.45)
        chunks_by_competitor: Dict[str, List[str]] = {}
        source_chunk_counts: Dict[str, int] = {}
        for artifact in artifacts:
            source_chunks = chunk_text(artifact.cleaned_text, self.config.chunk_size, self.config.chunk_overlap)
            focused_chunks = select_focused_chunks(
                source_chunks,
                template.parameters,
                research_type,
                self.config.max_llm_chunks_per_competitor,
            )
            chunks_by_competitor[artifact.competitor] = focused_chunks
            source_chunk_counts[artifact.competitor] = len(source_chunks)
            run.log(
                "INFO",
                f"Выбрано релевантных chunks для LLM: {len(focused_chunks)} из {len(source_chunks)}.",
                "Chunking",
                artifact.competitor,
            )
        run.stage("Chunking").finish(
            StageStatus.SUCCESS,
            chunks=sum(len(chunks) for chunks in chunks_by_competitor.values()),
            source_chunks=sum(source_chunk_counts.values()),
        )

        self._stage(run, "LLM extraction", "Извлекаю структурированные факты и evidence.", on_event, 0.50)
        raw_cells_by_competitor: Dict[str, List[EvidenceCell]] = {}
        for artifact in artifacts:
            raw_cells: List[EvidenceCell] = []
            chunks = chunks_by_competitor.get(artifact.competitor, [])
            for chunk_index, chunk in enumerate(chunks, start=1):
                prompt = build_extraction_prompt(artifact.competitor, artifact.url, research_type, template.parameters, chunk)
                cache_key = f"parser_v12_resilient_sources|{EXTRACTION_PROMPT_VERSION}|{artifact.url}|{template.parameters}|{chunk_index}|{chunk[:600]}"
                payload = self.cache.get("llm_extraction", cache_key)
                if payload is None:
                    self._progress_log(
                        run,
                        on_event,
                        "LLM extraction",
                        artifact.competitor,
                        f"Chunk {chunk_index}/{len(chunks)} отправлен в модель, жду ответ.",
                        0.50,
                    )
                    payload = self._complete_json_with_fallback(prompt, run, "LLM extraction", artifact.competitor)
                    self.cache.set("llm_extraction", cache_key, payload)
                else:
                    run.log("INFO", f"Chunk {chunk_index}/{len(chunks)} взят из кэша.", "LLM extraction", artifact.competitor)
                raw_cells.extend(cells_from_llm_payload(payload, artifact.url))
                run.log("INFO", f"Chunk {chunk_index}/{len(chunks)} обработан.", "LLM extraction", artifact.competitor)
            raw_cells_by_competitor[artifact.competitor] = raw_cells
        run.stage("LLM extraction").finish(StageStatus.SUCCESS, cells=sum(len(cells) for cells in raw_cells_by_competitor.values()))

        self._stage(run, "Нормализация", "Привожу значения к единому формату.", on_event, 0.68)
        normalized: Dict[str, Dict[str, EvidenceCell]] = {}
        for artifact in artifacts:
            normalized[artifact.competitor] = align_cells_to_schema(
                raw_cells_by_competitor.get(artifact.competitor, []),
                template.parameters,
                artifact.url,
                artifact.extraction_method,
            )
        run.cells = normalized
        run.stage("Нормализация").finish(StageStatus.SUCCESS)

        self._finish_simple_stage(run, "Schema alignment", on_event, 0.74, parameters=len(template.parameters))
        self._finish_simple_stage(run, "Построение таблицы", on_event, 0.78, rows=len(run.cells))

        self._stage(run, "Проверка конфликтов", "Проверяю спорные, отсутствующие и низкоуверенные значения.", on_event, 0.82)
        conflicts = detect_conflicts(run.cells)
        status = StageStatus.WARNING if conflicts else StageStatus.SUCCESS
        run.stage("Проверка конфликтов").finish(status, conflicts=sum(len(v) for v in conflicts.values()))
        run.insights["conflicts"] = conflicts

        self._stage(run, "Генерация выводов", "Генерирую сравнение Т-Банка с рынком и сравнение компаний по параметрам.", on_event, 0.88)
        run.insights.update(self.generate_insights(run, detail_level))
        run.stage("Генерация выводов").finish(StageStatus.SUCCESS)

        self._stage(run, "Экспорт", "Сохраняю JSON-версию исследования.", on_event, 0.96)
        self.storage.save_run(run)
        run.stage("Экспорт").finish(StageStatus.SUCCESS, path=str(self.config.runs_dir / f"{run.run_id}.json"))
        self.storage.save_run(run)
        if on_event:
            on_event(run, "Готово", "Исследование сохранено и готово к проверке и экспорту.", 1.0)
        return run

    def generate_insights(self, run: ResearchRun, detail_level: str) -> Dict[str, object]:
        compact_table = {
            competitor: {
                field: {
                    "value": cell.normalized_value or cell.extracted_value,
                    "status": cell.status.value,
                    "confidence": cell.confidence_score,
                }
                for field, cell in fields.items()
            }
            for competitor, fields in run.cells.items()
        }
        prompt = build_analytics_prompt(
            run.title,
            run.research_type,
            json.dumps(compact_table, ensure_ascii=False),
            detail_level,
            has_tbank=has_tbank_competitor(list(run.cells.keys())),
        )
        payload = self._complete_json_with_fallback(prompt, run, "Генерация выводов", "")
        if not payload or "parameter_comparison" not in payload:
            payload = heuristic_insights(compact_table)
        if not has_tbank_competitor(list(run.cells.keys())):
            payload["tbank_vs_market"] = []
        return payload

    def _source_cache_key(self, competitor: CompetitorInput) -> str:
        if competitor.manual_text.strip() or competitor.uploaded_text.strip() or not competitor.url.strip():
            return ""
        return (
            "source_v2|"
            f"{competitor.display_name()}|{competitor.url.strip()}|"
            f"{self.config.playwright_networkidle_timeout_ms}|"
            f"{self.config.browser_interaction_budget_seconds}|"
            f"{self.config.accordion_budget_seconds}|"
            f"{self.config.tabs_budget_seconds}"
        )

    def _complete_json_with_fallback(self, prompt: str, run: ResearchRun, stage: str, competitor: str) -> Dict[str, object]:
        try:
            return self.llm.complete_json(prompt)
        except Exception as exc:
            run.log(
                "ERROR",
                f"Ошибка LLM-провайдера: {exc}. Pipeline продолжит работу в эвристическом режиме с низкой уверенностью.",
                stage,
                competitor,
            )
            return self.fallback_llm.complete_json(prompt)

    def _stage(self, run: ResearchRun, name: str, message: str, on_event: Optional[UIEvent], progress: float) -> None:
        stage = run.stage(name)
        stage.start(message)
        run.log("INFO", message, name)
        if on_event:
            on_event(run, name, message, progress)

    def _finish_simple_stage(self, run: ResearchRun, name: str, on_event: Optional[UIEvent], progress: float, **metrics: object) -> None:
        self._stage(run, name, "Этап выполнен.", on_event, progress)
        run.stage(name).finish(StageStatus.SUCCESS, **metrics)

    def _progress_log(self, run: ResearchRun, on_event: Optional[UIEvent], stage: str, competitor: str, message: str, progress: float) -> None:
        run.log("INFO", message, stage, competitor)
        if on_event:
            on_event(run, stage, f"{competitor}: {message}", min(progress, 0.95))


def heuristic_insights(table: Dict[str, Dict[str, Dict[str, object]]]) -> Dict[str, object]:
    competitors = list(table.keys())
    fields = []
    for competitor_fields in table.values():
        for field in competitor_fields.keys():
            if field not in fields:
                fields.append(field)

    parameter_comparison = []
    for field in fields:
        available = [
            (competitor, str(table.get(competitor, {}).get(field, {}).get("value", "") or ""))
            for competitor in competitors
        ]
        available = [(competitor, value) for competitor, value in available if value]
        if len(available) < 2:
            parameter_comparison.append(
                f"По {field} невозможно надёжно определить лучшие и худшие условия: недостаточно данных у конкурентов."
            )
            continue
        values_text = "; ".join(f"{competitor}: {value}" for competitor, value in available)
        parameter_comparison.append(
            f"По {field} требуется экспертная проверка лучших и худших условий: {values_text}."
        )

    tbank_vs_market = []
    if has_tbank_competitor(competitors):
        tbank_name = next(name for name in competitors if is_tbank_name(name))
        for field in fields:
            tbank_value = table.get(tbank_name, {}).get(field, {}).get("value", "")
            if not tbank_value:
                tbank_vs_market.append(f"Т-Банк хуже конкурентов по параметру «{field}»: данные по Т-Банку не найдены.")
            else:
                tbank_vs_market.append(
                    f"Т-Банк наравне с конкурентами по параметру «{field}»: значение требует экспертной проверки на основе таблицы."
                )

    return {
        "tbank_vs_market": tbank_vs_market,
        "parameter_comparison": parameter_comparison,
    }


def has_tbank_competitor(competitors: List[str]) -> bool:
    return any(is_tbank_name(name) for name in competitors)


def is_tbank_name(name: str) -> bool:
    normalized = name.lower().replace("ё", "е").replace("-", "").replace(" ", "")
    return normalized in {"тбанк", "tbank", "тинькофф", "тинькоффбанк"} or "тбанк" in normalized or "tbank" in normalized
