"""HTTP contracts, separate from the immutable recorded agent contract."""
from typing import Any, Literal
from pydantic import Field, field_serializer, model_validator
from .core import Claim, ClaimResult, StrictModel, jsonable


class EvaluationRequest(StrictModel):
    mode: Literal["rules", "replay", "live"] = "rules"
    claim_ids: list[str] | None = Field(default=None, min_length=1, max_length=50)
    claims: list[Claim] | None = Field(default=None, min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.claim_ids is not None and self.claims is not None:
            raise ValueError("Provide claim_ids or claims, never both")
        ids = self.claim_ids if self.claim_ids is not None else [c.claim_id for c in self.claims or []]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate claim IDs are not allowed")
        return self


class EvaluationEnvelope(StrictModel):
    claim: Claim
    result: ClaimResult
    audit: dict[str, Any]

    @field_serializer("claim", "result")
    def numeric_money(self, value):
        return jsonable(value)


class EvaluationJob(StrictModel):
    job_id: str
    mode: Literal["rules", "replay", "live"]
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    claim_ids: list[str]
    completed_count: int = 0
    evaluations: list[EvaluationEnvelope] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    finished_at: str | None = None


class EvaluationSnapshot(StrictModel):
    evaluations: list[EvaluationEnvelope]
    policy_version: str
