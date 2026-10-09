"""Executable HTTP boundary for release diagnostics."""

from fastapi import FastAPI, HTTPException

from release_diagnostics import BuildEvent, InfraiError, ReleaseDiagnostic, service_from_environment


app = FastAPI(title="Release cost diagnostics")


@app.post("/release-diagnostics", response_model=ReleaseDiagnostic)
def create_release_diagnostic(event: BuildEvent) -> ReleaseDiagnostic:
    try:
        return service_from_environment().review(event)
    except InfraiError as exc:
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
