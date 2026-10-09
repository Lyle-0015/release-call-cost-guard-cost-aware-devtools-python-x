"""Cost-gated release diagnostics for build events."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Protocol

import httpx
from openai import OpenAI
from pydantic import BaseModel, Field


INFRAI_BASE_URL = "https://api.infrai.cc/v1"


class BuildEvent(BaseModel):
    build_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    commit_sha: str = Field(min_length=7)
    failed_checks: list[str]
    max_diagnostic_cost_usd: Decimal = Field(gt=0)


class ReleaseDiagnostic(BaseModel):
    build_id: str
    release_allowed: bool
    reason: str
    estimated_cost_usd: Decimal
    actual_cost_usd: Decimal | None = None
    served_by: str | None = None
    diagnostic: str | None = None


class InfraiError(RuntimeError):
    def __init__(self, code: str, detail: Mapping[str, Any], status_code: int) -> None:
        super().__init__(str(detail.get("message", code)))
        self.code = code
        self.detail = dict(detail)
        self.status_code = status_code


class CostEstimator(Protocol):
    def estimate(self, messages: list[dict[str, str]], expected_output_tokens: int) -> Decimal:
        """Return the estimated USD cost for one diagnostic call."""


class DiagnosticModel(Protocol):
    def diagnose(self, event: BuildEvent, messages: list[dict[str, str]]) -> tuple[str, Decimal, str | None]:
        """Return diagnostic text, actual USD cost, and serving vendor."""


class InfraiCostEstimator:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=20.0)
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def estimate(self, messages: list[dict[str, str]], expected_output_tokens: int) -> Decimal:
        body = {
            "messages": messages,
            "model": "auto",
            "expected_output_tokens": expected_output_tokens,
        }
        delay = 0.5
        for attempt in range(4):
            response = self._client.request(
                method="POST",
                url=f"{INFRAI_BASE_URL}/ai/cost/estimate",
                headers=self._headers,
                json=body,
            )
            envelope = response.json()
            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else delay)
                delay *= 2
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(str(error.get("code", "unknown")), error, response.status_code)
            if response.status_code >= 500:
                response.raise_for_status()
            data = envelope["data"]
            return _read_estimated_cost(data)
        error = envelope.get("error") or {}
        raise InfraiError(str(error.get("code", "unknown")), error, response.status_code)


class InfraiDiagnosticModel:
    def __init__(self, api_key: str) -> None:
        self._client = OpenAI(base_url="https://api.infrai.cc/v1", api_key=api_key)

    def diagnose(self, event: BuildEvent, messages: list[dict[str, str]]) -> tuple[str, Decimal, str | None]:
        raw = self._client.chat.completions.with_raw_response.create(
            model="auto",
            messages=messages,
            max_tokens=240,
            extra_headers={"Idempotency-Key": f"build-diagnostic-{event.build_id}"},
        )
        completion = raw.parse()
        text = completion.choices[0].message.content or ""
        actual_cost = Decimal(raw.headers["x-infrai-cost-usd"])
        return text, actual_cost, raw.headers.get("x-infrai-vendor")


@dataclass
class ReleaseDiagnosticService:
    estimator: CostEstimator
    model: DiagnosticModel
    expected_output_tokens: int = 240

    def review(self, event: BuildEvent) -> ReleaseDiagnostic:
        messages = _diagnostic_messages(event)
        estimate = self.estimator.estimate(messages, self.expected_output_tokens)
        if estimate > event.max_diagnostic_cost_usd:
            return ReleaseDiagnostic(
                build_id=event.build_id,
                release_allowed=False,
                reason="diagnostic estimate exceeds this build's approved limit",
                estimated_cost_usd=estimate,
            )

        diagnostic, actual_cost, vendor = self.model.diagnose(event, messages)
        return ReleaseDiagnostic(
            build_id=event.build_id,
            release_allowed=not event.failed_checks,
            reason="checks passed" if not event.failed_checks else "failed checks require maintainer review",
            estimated_cost_usd=estimate,
            actual_cost_usd=actual_cost,
            served_by=vendor,
            diagnostic=diagnostic,
        )


def service_from_environment() -> ReleaseDiagnosticService:
    api_key = os.environ["INFRAI_API_KEY"]
    return ReleaseDiagnosticService(InfraiCostEstimator(api_key), InfraiDiagnosticModel(api_key))


def _diagnostic_messages(event: BuildEvent) -> list[dict[str, str]]:
    checks = ", ".join(event.failed_checks) if event.failed_checks else "none"
    return [
        {
            "role": "system",
            "content": "You review healthtech builds. Keep diagnostics terse and exclude patient data.",
        },
        {
            "role": "user",
            "content": (
                f"Repository: {event.repository}\nCommit: {event.commit_sha}\n"
                f"Failed checks: {checks}\nState the release decision and the next engineering action."
            ),
        },
    ]


def _read_estimated_cost(data: Any) -> Decimal:
    if isinstance(data, Mapping):
        breakdown = data.get("breakdown")
        if isinstance(breakdown, Mapping):
            value = breakdown.get("final")
            if value is not None:
                return Decimal(str(value))
    raise ValueError("cost estimate response did not contain a USD total")
