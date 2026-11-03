"""Pydantic schema handed to LangChain structured output. Loosely typed on purpose (str enums):
invalid categories/severities are discarded and counted by services.finding_validation instead of
failing the whole model call."""
from pydantic import BaseModel, Field


class LLMFinding(BaseModel):
    category: str = Field(description="bug | security | performance | maintainability | testing")
    severity: str = Field(description="critical | high | medium | low | info")
    title: str
    explanation: str
    evidence: str = Field(description="One exact line copied from the diff")
    path: str
    start_line: int | None = None
    end_line: int | None = None
    remediation: str | None = None
    patch: str | None = None
    confidence: float = Field(description="0.0 to 1.0")


class LLMReviewOutput(BaseModel):
    findings: list[LLMFinding] = Field(default_factory=list)
