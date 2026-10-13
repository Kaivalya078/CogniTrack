from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_session

router = APIRouter()


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    db: str


@router.get("/health")
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> Health:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        response.status_code = 503
        return Health(status="degraded", db=type(exc).__name__)
    return Health(status="ok", db="ok")
