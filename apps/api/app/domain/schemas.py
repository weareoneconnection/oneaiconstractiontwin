from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    code: str
    description: str = ""


class ProjectOut(ProjectCreate):
    id: str
    tenant_id: str
    organization_id: str
    planned_progress: float
    actual_progress: float
    forecast_delay_days: float
    model_config = {"from_attributes": True}


class TwinEntityCreate(BaseModel):
    entity_type: str
    name: str
    external_ids: dict[str, Any] = Field(default_factory=dict)
    spatial: dict[str, Any] = Field(default_factory=dict)
    lifecycle: dict[str, Any] = Field(default_factory=dict)
    links: dict[str, Any] = Field(default_factory=dict)
    intelligence: dict[str, Any] = Field(default_factory=dict)


class TwinEntityOut(TwinEntityCreate):
    id: str
    project_id: str
    version: int
    model_config = {"from_attributes": True}


class AskRequest(BaseModel):
    question: str


class EvidenceRef(BaseModel):
    id: str
    source_type: str
    source_id: str
    content: str
    confidence: float
    relevance: float = 0.0
    matched_terms: list[str] = Field(default_factory=list)


class AskResponse(BaseModel):
    question: str = ""
    answer: str
    confidence: float
    #: True when no project record matched the question. The answer must then be
    #: treated as provisional and never used for a contractual decision.
    provisional: bool = False
    evidence_coverage: float = 0.0
    claims: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    risks: list[dict[str, Any]] = Field(default_factory=list)
    recommended_actions: list[dict[str, Any]] = Field(default_factory=list)
    #: Provenance of the answer: which provider and model produced it, and whether
    #: a real model was involved at all.
    reasoning: dict[str, Any] = Field(default_factory=dict)


class SimulationRequest(BaseModel):
    scenario: str
    delay_days: int = 7
    cost_per_day: float = 60000
    recovery_efficiency: float = 0.65


class SimulationResponse(BaseModel):
    scenario: str
    schedule_impact_days: float
    cost_impact: float
    risk_delta: float
    options: list[dict[str, Any]]
    model: str = ""
    calibrated: bool = False
    assumptions: list[dict[str, Any]] = Field(default_factory=list)


class AgentRunRequest(BaseModel):
    agent: str = "project_director"
    task: str = "Review current project status"


class AgentActionOut(BaseModel):
    id: str
    agent: str
    action_type: str
    payload: dict[str, Any]
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}


class AssetBuildJobRequest(BaseModel):
    longitude: float = 101.6869
    latitude: float = 3.1390
    height: float = 0.0
    partition_max_entities: int = Field(default=64, ge=1, le=1000)
    partition_max_triangles: int = Field(default=1_000_000, ge=1_000)
    max_triangles_per_entity: int = Field(default=120_000, ge=1_000)
    compression: str = "none"
    force_rebuild: bool = False
