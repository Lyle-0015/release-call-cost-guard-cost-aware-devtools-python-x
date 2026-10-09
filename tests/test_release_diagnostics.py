from decimal import Decimal

import httpx

from release_diagnostics import BuildEvent, InfraiCostEstimator, ReleaseDiagnosticService


class FixedEstimator:
    def __init__(self, cost: str) -> None:
        self.cost = Decimal(cost)

    def estimate(self, messages: list[dict[str, str]], expected_output_tokens: int) -> Decimal:
        assert "patient data" in messages[0]["content"]
        assert expected_output_tokens == 240
        return self.cost


class RecordingModel:
    def __init__(self) -> None:
        self.calls = 0

    def diagnose(self, event: BuildEvent, messages: list[dict[str, str]]) -> tuple[str, Decimal, str]:
        self.calls += 1
        return "Hold release; inspect the failing privacy scan.", Decimal("0.0041"), "example-vendor"


def test_live_estimate_response_reads_final_usd_cost() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/ai/cost/estimate"
        return httpx.Response(200, json={"ok": True, "data": {"breakdown": {"currency": "USD", "final": 0.00118598}}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        estimate = InfraiCostEstimator("test-key", client).estimate(
            [{"role": "user", "content": "Check build"}], 240
        )

    assert estimate == Decimal("0.00118598")


def test_release_is_held_before_model_call_when_estimate_exceeds_limit() -> None:
    model = RecordingModel()
    service = ReleaseDiagnosticService(FixedEstimator("0.031"), model)
    event = BuildEvent(
        build_id="build-1842",
        repository="clinical-exporter",
        commit_sha="9f40a2c",
        failed_checks=["privacy-scan"],
        max_diagnostic_cost_usd=Decimal("0.020"),
    )

    result = service.review(event)

    assert result.release_allowed is False
    assert result.estimated_cost_usd == Decimal("0.031")
    assert result.actual_cost_usd is None
    assert model.calls == 0


def test_failed_check_is_visible_after_an_approved_model_call() -> None:
    model = RecordingModel()
    service = ReleaseDiagnosticService(FixedEstimator("0.003"), model)
    event = BuildEvent(
        build_id="build-1843",
        repository="clinical-exporter",
        commit_sha="20b4f11",
        failed_checks=["privacy-scan"],
        max_diagnostic_cost_usd=Decimal("0.020"),
    )

    result = service.review(event)

    assert result.release_allowed is False
    assert result.actual_cost_usd == Decimal("0.0041")
    assert result.served_by == "example-vendor"
    assert model.calls == 1
