"""Typer CLI for local ingestion, temporal queries, replay, and evaluation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic_core import to_jsonable_python

from chronograph_ai.engine import ChronoGraphEngine
from chronograph_ai.evaluation import run_evaluation
from chronograph_ai.integrity import IntegrityChecker
from chronograph_ai.memory import MemoryAssembler
from chronograph_ai.models import EpisodeCreate, EpisodeSource, MemoryRequest
from chronograph_ai.replay import replay as replay_episodes
from chronograph_ai.retrieval import HybridRetriever
from chronograph_ai.storage import SQLiteGraphStore

app = typer.Typer(
    name="chronograph",
    help="ChronoGraph temporal knowledge and governed memory engine.",
    no_args_is_help=True,
)


class CliState:
    def __init__(self, database: Path) -> None:
        self.database = database


@app.callback()
def main(
    ctx: typer.Context,
    database: Annotated[
        Path,
        typer.Option("--db", help="SQLite state path for local commands."),
    ] = Path("chronograph.db"),
) -> None:
    """Configure the local deterministic SQLite store."""

    ctx.obj = CliState(database)


def _engine(ctx: typer.Context) -> ChronoGraphEngine:
    state = ctx.ensure_object(CliState)
    return ChronoGraphEngine(store=SQLiteGraphStore(state.database))


def _emit(value: Any) -> None:
    typer.echo(json.dumps(to_jsonable_python(value), indent=2, sort_keys=True))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise typer.BadParameter("timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _load_episodes(path: Path) -> list[EpisodeCreate]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        values = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        parsed = json.loads(raw)
        values = parsed if isinstance(parsed, list) else [parsed]
    return [EpisodeCreate.model_validate(value) for value in values]


@app.command()
def ingest(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Ingest a validated JSON or JSONL episode fixture."""

    engine = _engine(ctx)
    _emit([engine.ingest(payload).model_dump(mode="json") for payload in _load_episodes(file)])


@app.command()
def entity(ctx: typer.Context, entity_id: str) -> None:
    """Show one entity by identifier."""

    value = _engine(ctx).store.get_entity(entity_id)
    if value is None:
        raise typer.BadParameter("entity not found")
    _emit(value)


@app.command()
def history(ctx: typer.Context, entity_id: str) -> None:
    """Show the complete fact history for an entity."""

    try:
        _emit([fact.model_dump(mode="json") for fact in _engine(ctx).entity_history(entity_id)])
    except KeyError as exc:
        raise typer.BadParameter("entity not found") from exc


@app.command("query")
def query_command(
    ctx: typer.Context,
    text: str,
    at: Annotated[str | None, typer.Option(help="Valid-time ISO 8601 timestamp.")] = None,
    known_at: Annotated[
        str | None, typer.Option(help="Optional system-time ISO 8601 timestamp.")
    ] = None,
    entity_id: Annotated[str | None, typer.Option(help="Optional graph anchor entity.")] = None,
    limit: Annotated[int, typer.Option(min=1, max=100)] = 20,
) -> None:
    """Run explainable hybrid retrieval over temporally valid facts."""

    engine = _engine(ctx)
    results = HybridRetriever(engine).search(
        text,
        valid_time=_parse_time(at) if at else engine.clock(),
        known_at=_parse_time(known_at) if known_at else None,
        anchor_entity_id=entity_id,
        max_results=limit,
    )
    _emit([result.model_dump(mode="json") for result in results])


@app.command("as-of")
def as_of(
    ctx: typer.Context,
    timestamp: str,
    query: str,
    known_at: Annotated[
        str | None, typer.Option(help="Optional system-time ISO 8601 timestamp.")
    ] = None,
) -> None:
    """Search the graph at a valid-time instant with an optional known-at lens."""

    engine = _engine(ctx)
    results = HybridRetriever(engine).search(
        query,
        valid_time=_parse_time(timestamp),
        known_at=_parse_time(known_at) if known_at else None,
    )
    _emit([result.model_dump(mode="json") for result in results])


@app.command()
def memory(
    ctx: typer.Context,
    entity_id: str,
    query: Annotated[str, typer.Option("--query")],
    at: Annotated[str | None, typer.Option(help="Current-time ISO 8601 timestamp.")] = None,
) -> None:
    """Assemble a bounded evidence-backed memory bundle."""

    engine = _engine(ctx)
    request = MemoryRequest(
        agent_id="chronograph-cli",
        subject_entity_id=entity_id,
        query=query,
        current_time=_parse_time(at) if at else engine.clock(),
    )
    _emit(MemoryAssembler(engine).assemble(request))


@app.command()
def replay(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Replay ordered fixtures into a fresh deterministic graph and print its digest."""

    engine, state_digest = replay_episodes(_load_episodes(file))
    _emit({"digest": state_digest, "stats": engine.stats()})


@app.command("eval")
def evaluate() -> None:
    """Run the deterministic evaluation scenarios; no benchmark is produced."""

    results = run_evaluation()
    _emit([result.model_dump(mode="json") for result in results])
    if not all(result.passed for result in results):
        raise typer.Exit(code=1)


@app.command()
def stats(ctx: typer.Context) -> None:
    """Show local store record counts."""

    _emit(_engine(ctx).stats())


@app.command()
def integrity(ctx: typer.Context) -> None:
    """Validate graph references, temporal intervals, provenance, and cycles."""

    engine = _engine(ctx)
    report = IntegrityChecker(engine.store, engine.ontology, engine.clock).check()
    _emit(report)
    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def demo() -> None:
    """Run the local Alice employment and governed-memory demonstration."""

    engine = ChronoGraphEngine()
    first = EpisodeCreate(
        source_type=EpisodeSource.STRUCTURED_RECORD,
        source_id="demo-acme",
        content="Alice works at Acme.",
        event_time=_parse_time("2026-01-01T00:00:00Z"),
        observed_at=_parse_time("2026-01-01T00:00:00Z"),
        idempotency_key="demo-acme",
    )
    second = EpisodeCreate(
        source_type=EpisodeSource.STRUCTURED_RECORD,
        source_id="demo-orbit",
        content="Alice now works at Orbit.",
        event_time=_parse_time("2026-02-01T00:00:00Z"),
        observed_at=_parse_time("2026-02-01T00:00:00Z"),
        idempotency_key="demo-orbit",
    )
    engine.ingest(first)
    engine.ingest(second)
    alice = next(
        entity for entity in engine.store.list_entities() if entity.canonical_name == "Alice"
    )
    current_time = _parse_time("2026-03-01T00:00:00Z")
    memory_bundle = MemoryAssembler(engine).assemble(
        MemoryRequest(
            agent_id="demo-agent",
            subject_entity_id=alice.id,
            query="Alice employer",
            current_time=current_time,
        )
    )
    _emit(
        {
            "current": [
                fact.model_dump(mode="json")
                for fact in engine.facts_valid_at(current_time, entity_id=alice.id)
            ],
            "historical": [
                fact.model_dump(mode="json")
                for fact in engine.facts_valid_at(
                    _parse_time("2026-01-15T00:00:00Z"), entity_id=alice.id
                )
            ],
            "provenance": engine.provenance(engine.store.list_facts()[-1].id),
            "memory": memory_bundle.model_dump(mode="json"),
        }
    )


if __name__ == "__main__":
    app()
