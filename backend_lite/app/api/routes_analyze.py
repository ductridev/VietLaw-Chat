from __future__ import annotations

from fastapi import APIRouter, Depends

from ..dependencies import AppContainer, get_container
from ..schemas.api import AnalyzeRequest, AnalyzeResponse

router = APIRouter(prefix="/api", tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    payload: AnalyzeRequest,
    container: AppContainer = Depends(get_container),
) -> AnalyzeResponse:
    return await container.runtime.analyze(payload)
