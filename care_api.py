"""Care workspace APIs, for the local website only."""
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
import care_journey

router=APIRouter(prefix='/care/api')

class ActionRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:str
    staff:str=Field(default='',max_length=100)
    note:str=Field(default='',max_length=2000)
    outcome:str='worsening'
    delay_seconds:float=Field(default=8,ge=1,le=3600)
    expected_revision:int|None=None
    message_id:str|None=None


def invoke(function,*args,**kwargs):
    try:
        return function(*args,**kwargs)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None

@router.get('/state')
async def state():
    return invoke(care_journey.load_state)

@router.get('/scheduler')
async def scheduler():
    return care_journey.scheduler_status()

@router.post('/action')
async def action(body:ActionRequest):
    return invoke(care_journey.action,**body.model_dump())

@router.get('/intake.pdf')
async def intake_pdf():
    return Response(invoke(care_journey.intake_pdf),media_type='application/pdf',
                    headers={'Content-Disposition':'inline; filename="Meera-Sharma-history.pdf"'})
