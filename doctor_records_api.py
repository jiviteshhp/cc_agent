"""Local-only prepared records, printed documents and staff review actions."""
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import doctor_records

router = APIRouter(prefix="/doctor/api")


class StaffAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    staff: str = Field(min_length=1, max_length=100)
    expected_revision: int | None = Field(default=None, ge=0)


class DispositionAction(StaffAction):
    note: str = Field(min_length=1, max_length=2000)


class RoutingAction(StaffAction):
    vision_room: str = Field(min_length=1, max_length=40)
    nct_room: str = Field(min_length=1, max_length=40)


class ResetAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None = Field(default=None, ge=0)


def invoke(function, **kwargs):
    try:
        return function(**kwargs)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else "This prepared record could not be loaded."
        raise HTTPException(409, detail) from None


def result(value):
    return JSONResponse(value, headers={"Cache-Control": "no-store"})


@router.get("/workspace")
async def workspace():
    return result(invoke(doctor_records.workspace))


@router.get("/reports/prepared/pdf")
async def report_pdf(download: bool = False):
    return Response(invoke(doctor_records.report_pdf), media_type="application/pdf",
                    headers={"Cache-Control": "no-store", "Content-Disposition":
                             ("attachment" if download else "inline") + '; filename="Meera-Sharma-history.pdf"'})


@router.get("/reports/prepared/visit.pdf")
async def visit_pdf(download: bool = False):
    return Response(invoke(doctor_records.visit_pdf), media_type="application/pdf",
                    headers={"Cache-Control": "no-store", "Content-Disposition":
                             ("attachment" if download else "inline") + '; filename="Meera-Sharma-visit-route.pdf"'})


@router.post("/aftercare/acknowledge")
async def acknowledge(body: StaffAction):
    return result(invoke(doctor_records.acknowledge, **body.model_dump()))


@router.post("/aftercare/disposition")
async def disposition(body: DispositionAction):
    return result(invoke(doctor_records.record_disposition, **body.model_dump()))


@router.post("/routing")
async def routing(body: RoutingAction):
    return result(invoke(doctor_records.update_routing, **body.model_dump()))


@router.post("/prepared/reset")
async def reset(body: ResetAction):
    return result(invoke(doctor_records.reset_prepared, **body.model_dump()))
