"""Typed FastAPI surface for implemented ChronoGraph behavior."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from chronograph_ai import __version__
from chronograph_ai.auth import AllowAllAuthProvider, AuthProvider
from chronograph_ai.engine import ChronoGraphEngine
from chronograph_ai.integrity import IntegrityChecker
from chronograph_ai.memory import MemoryAssembler
from chronograph_ai.models import (
    Entity,
    EntityMergeProposal,
    Episode,
    EpisodeCreate,
    Fact,
    FactEvidence,
    GraphQuery,
    GraphSnapshot,
    HealthResponse,
    IngestionResult,
    IntegrityReport,
    MemoryBundle,
    MemoryRequest,
    SearchResult,
    StrictModel,
)
from chronograph_ai.retrieval import HybridRetriever


class MergeProposalRequest(StrictModel):
    source_entity_id: str
    target_entity_id: str
    reason: str
    evidence_episode_ids: list[str]


class MergeDecisionRequest(StrictModel):
    reason: str


class ProvenanceResponse(StrictModel):
    fact: Fact
    evidence: list[FactEvidence]
    episodes: list[Episode]
    supersession_chain: list[Fact]


def create_app(
    engine: ChronoGraphEngine | None = None,
    *,
    auth_provider: AuthProvider | None = None,
) -> FastAPI:
    graph = engine or ChronoGraphEngine()
    auth = auth_provider or AllowAllAuthProvider()

    async def authorize(request: Request) -> None:
        await auth.authorize(request)

    app = FastAPI(
        title="ChronoGraph AI",
        version=__version__,
        description="Temporal knowledge and governed agent-memory API",
        dependencies=[Depends(authorize)],
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__, backend=graph.store.backend_name)

    @app.post("/episodes", response_model=IngestionResult, status_code=201)
    def ingest_episode(payload: EpisodeCreate) -> IngestionResult:
        try:
            return graph.ingest(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/episodes/{episode_id}", response_model=Episode)
    def get_episode(episode_id: str) -> Episode:
        episode = graph.store.get_episode(episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail="episode not found")
        return episode

    @app.get("/entities/{entity_id}", response_model=Entity)
    def get_entity(entity_id: str) -> Entity:
        entity = graph.store.get_entity(entity_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return entity

    @app.get("/entities/{entity_id}/history", response_model=list[Fact])
    def entity_history(entity_id: str) -> list[Fact]:
        try:
            return graph.entity_history(entity_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="entity not found") from exc

    @app.get("/entities/{entity_id}/neighbors", response_model=list[Entity])
    def entity_neighbors(
        entity_id: str,
        at: Annotated[datetime, Query(description="Valid-time instant")],
        known_at: Annotated[datetime | None, Query(description="Optional system-time lens")] = None,
        predicate: Annotated[list[str] | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[Entity]:
        if graph.store.get_entity(entity_id) is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return graph.neighbors(
            entity_id,
            valid_time=at,
            known_at=known_at,
            predicates=set(predicate) if predicate else None,
            limit=limit,
        )

    @app.post("/query", response_model=list[SearchResult])
    def query(payload: GraphQuery) -> list[SearchResult]:
        return HybridRetriever(graph).search(
            payload.text,
            valid_time=payload.valid_time or graph.clock(),
            known_at=payload.known_at,
            anchor_entity_id=payload.entity_id,
            predicate=payload.predicate,
            max_depth=payload.max_depth,
            max_results=payload.max_results,
        )

    @app.post("/query/as-of", response_model=GraphSnapshot)
    def query_as_of(payload: GraphQuery) -> GraphSnapshot:
        if payload.valid_time is None:
            raise HTTPException(status_code=422, detail="valid_time is required")
        return graph.graph_as_of(payload.valid_time, known_at=payload.known_at)

    @app.get("/facts/{fact_id}", response_model=Fact)
    def get_fact(fact_id: str) -> Fact:
        fact = graph.store.get_fact(fact_id)
        if fact is None:
            raise HTTPException(status_code=404, detail="fact not found")
        return fact

    @app.get("/facts/{fact_id}/provenance", response_model=ProvenanceResponse)
    def fact_provenance(fact_id: str) -> ProvenanceResponse:
        try:
            return ProvenanceResponse.model_validate(graph.provenance(fact_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="fact not found") from exc

    @app.post("/entities/merge-proposals", response_model=EntityMergeProposal)
    def create_merge_proposal(payload: MergeProposalRequest) -> EntityMergeProposal:
        try:
            return graph.propose_merge(
                payload.source_entity_id,
                payload.target_entity_id,
                reason=payload.reason,
                evidence_episode_ids=payload.evidence_episode_ids,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="merge entity not found") from exc

    @app.post(
        "/entities/merge-proposals/{proposal_id}/approve",
        response_model=EntityMergeProposal,
    )
    def approve_merge(proposal_id: str, payload: MergeDecisionRequest) -> EntityMergeProposal:
        try:
            return graph.decide_merge(proposal_id, approve=True, reason=payload.reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="merge proposal not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/entities/merge-proposals/{proposal_id}/reject",
        response_model=EntityMergeProposal,
    )
    def reject_merge(proposal_id: str, payload: MergeDecisionRequest) -> EntityMergeProposal:
        try:
            return graph.decide_merge(proposal_id, approve=False, reason=payload.reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="merge proposal not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/memory/query", response_model=MemoryBundle)
    def memory_query(payload: MemoryRequest) -> MemoryBundle:
        return MemoryAssembler(graph).assemble(payload)

    @app.get("/integrity", response_model=IntegrityReport)
    def integrity() -> IntegrityReport:
        return IntegrityChecker(graph.store, graph.ontology, graph.clock).check()

    @app.get("/stats", response_model=dict[str, int | str])
    def stats() -> dict[str, int | str]:
        return graph.stats()

    app.state.chronograph = graph
    return app


app = create_app()
