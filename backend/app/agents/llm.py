"""LLM adapters. `analyze(messages) -> {"findings": [...]}` (raw, UNTRUSTED; validated downstream).

* OpenAIReviewLLM: LangChain ChatOpenAI + structured output (needs langchain-openai; NOT RUN offline).
* KeywordMockLLM: deterministic keyword matcher for local demos/tests. Not AI; always labelled as such.
There is NO automatic fallback from a failed real call to the mock.
"""
import re
from typing import TYPE_CHECKING

from app.core.exceptions import BadRequest, NotConfigured, RateLimited, UpstreamError

if TYPE_CHECKING:
    from app.core.config import Settings

_RETRIABLE = {"APITimeoutError", "APIConnectionError", "InternalServerError", "Timeout", "TimeoutError", "ConnectError", "ReadTimeout"}
_AUTH = {"AuthenticationError", "PermissionDeniedError"}
_BAD_OUTPUT = {"OutputParserException", "ValidationError"}


def map_provider_error(exc: Exception) -> Exception:
    """Provider exceptions -> app errors with correct retry semantics and no leaked details."""
    name = type(exc).__name__
    if name == "RateLimitError":
        return RateLimited("OpenAI rate limit or quota reached", code="openai_rate_limited")
    if name in _AUTH:
        return NotConfigured("OpenAI rejected the API key or permissions", code="openai_auth_failed")
    if name == "BadRequestError" or name == "ContextLengthExceededError":
        return BadRequest("OpenAI rejected the request (input may be too large)", code="openai_bad_request")
    if name in _BAD_OUTPUT:
        return UpstreamError("The model returned output that did not match the required schema", code="openai_invalid_output")
    if name in _RETRIABLE:
        return UpstreamError("OpenAI is temporarily unavailable", code="openai_unavailable")
    return UpstreamError("Unexpected error from the AI provider", code="openai_error")


class OpenAIReviewLLM:
    def __init__(self, s: "Settings"):
        from langchain_openai import ChatOpenAI

        from app.agents.review_schemas import LLMReviewOutput
        self.model_name = s.openai_model
        self._chain = ChatOpenAI(model=s.openai_model, api_key=s.openai_api_key, temperature=0, timeout=s.openai_timeout_seconds,
                                 max_retries=1).with_structured_output(LLMReviewOutput)

    def analyze(self, messages: list[dict]) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage
        msgs = [SystemMessage(content=m["content"]) if m["role"] == "system" else HumanMessage(content=m["content"]) for m in messages]
        try:
            out = self._chain.invoke(msgs)
        except Exception as exc:  # noqa: BLE001
            raise map_provider_error(exc) from exc
        return out.model_dump() if hasattr(out, "model_dump") else dict(out)


_PATTERNS = [
    (re.compile(r"\beval\(|\bexec\("), "security", "high", "Use of eval/exec on dynamic input", "Dynamic code execution can run attacker-controlled code.", "Avoid eval/exec; parse data explicitly."),
    (re.compile(r"(?i)execute\(.*['\"]\s*\+|execute\(f['\"]"), "security", "high", "SQL built by string concatenation", "Concatenated SQL may allow injection.", "Use parameterized queries."),
    (re.compile(r"(?i)except\s*:\s*(pass)?\s*$"), "bug", "medium", "Bare except hides errors", "A bare except swallows all errors including unexpected ones.", "Catch specific exceptions and log them."),
]


class KeywordMockLLM:
    model_name = "mock-llm (deterministic keyword matcher, not AI)"

    def analyze(self, messages: list[dict]) -> dict:
        text = messages[-1]["content"]
        findings, path = [], None
        for line in text.splitlines():
            if line.startswith("### FILE "):
                path = line[len("### FILE "):].rsplit(" (", 1)[0]
                continue
            m = re.match(r"L\s*(\d+)\| \+(.*)$", line)
            if not (path and m):
                continue
            for rx, cat, sev, title, expl, fix in _PATTERNS:
                if rx.search(m.group(2)):
                    n = int(m.group(1))
                    findings.append({"category": cat, "severity": sev, "title": title, "explanation": expl, "evidence": m.group(2).strip(),
                                     "path": path, "start_line": n, "end_line": n, "remediation": fix, "patch": None, "confidence": 0.7})
        return {"findings": findings}


def get_review_llm(s: "Settings"):
    if s.openai_configured:
        return OpenAIReviewLLM(s)
    if s.review_use_mock_llm:
        return KeywordMockLLM()
    raise NotConfigured("OpenAI is not configured. Set OPENAI_API_KEY (or REVIEW_USE_MOCK_LLM=true for a clearly labelled local mock).",
                        code="openai_not_configured")
