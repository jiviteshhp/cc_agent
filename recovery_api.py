"""Local synthetic recovery routes; never included on the public phone app."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
import recovery

router = APIRouter(prefix="/recovery/api")


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReplayRequest(StrictBody):
    branch: str


class StaffRequest(StrictBody):
    action: str
    staff: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)
    expected_revision: int | None = None


class ReportRequest(StrictBody):
    text: str = Field(max_length=8000)
    expected_revision: int | None = None


def _run(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/state")
async def state():
    return _run(recovery.load_state)


@router.get("/protocol")
async def protocol():
    return _run(recovery.protocol)


@router.post("/replay")
async def replay(request: ReplayRequest):
    return _run(recovery.replay, request.branch)


@router.post("/reset")
async def reset():
    return _run(recovery.reset)


@router.post("/staff")
async def staff(request: StaffRequest):
    return _run(recovery.staff_action, request.action, request.staff, request.note,
                expected_revision=request.expected_revision)


@router.post("/report")
async def report(request: ReportRequest):
    revision = recovery.load_state()["revision"] if request.expected_revision is None else request.expected_revision
    try:
        return await recovery.submit_live(request.text, mode="live_text", expected_revision=revision)
    except ValueError as exc:
        if "Demo changed" in str(exc):
            raise HTTPException(409, "Demo changed while extraction was running. Refresh and retry.") from None
    except Exception:
        pass
    # Keep the actual source and incomplete call visible; no fixture replaces failure.
    turns = [{"id": "failed-text-" + uuid4().hex[:12], "role": "patient", "text": request.text}]
    state = _run(recovery.process_report, turns,
                 {"observations": [], "uncertainties": ["Live extraction failed; patient source needs staff review."]},
                 mode="live_text", extraction_source="unavailable", expected_revision=revision)
    return JSONResponse(status_code=503, content={
        "detail": "Live extraction unavailable. Source saved for unresolved review; no replay was substituted.",
        "state": state})
