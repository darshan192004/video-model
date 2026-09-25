"""Job routes. The enqueue, detail, and cancel surface lands in Phase 1.5.5;
this phase ships the auth-guarded listing so the session contract is testable."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..deps import require_user
from ..models import User

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(user: Annotated[User, Depends(require_user)]) -> dict:
    return {"jobs": [], "owner": user.subject}
