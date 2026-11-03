from typing import Literal

import re

from pydantic import BaseModel, Field, field_validator

Severity = Literal["critical", "high", "medium", "low", "info"]


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    instruction: str = Field(min_length=10, max_length=2000)
    severity: Severity = "medium"
    file_patterns: list[str] = Field(default_factory=list, max_length=20)
    languages: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True
    repository_id: int | None = None


class RulePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    instruction: str | None = Field(None, min_length=10, max_length=2000)
    severity: Severity | None = None
    file_patterns: list[str] | None = Field(None, max_length=20)
    languages: list[str] | None = Field(None, max_length=20)
    enabled: bool | None = None


class RuleOut(BaseModel):
    id: int
    name: str
    description: str
    instruction: str
    severity: str
    file_patterns: list[str]
    languages: list[str]
    enabled: bool
    repository_id: int | None
    repository: str | None = None
    is_demo: bool
    editable: bool


class RuleTestIn(BaseModel):
    instruction: str = Field(min_length=10, max_length=2000)
    severity: Severity = "medium"
    file_name: str = Field("snippet.py", min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=6000)

    @field_validator("file_name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        if v.startswith("/") or ".." in v or not re.fullmatch(r"[\w.\-/]+", v):
            raise ValueError("Invalid file name")
        return v


class RuleTestOut(BaseModel):
    findings: list[dict]
    summary: str
    model: str
    mock: bool
    ai_generated: bool = True
