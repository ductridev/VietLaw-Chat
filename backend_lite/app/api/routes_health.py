from __future__ import annotations

from fastapi import APIRouter, Depends

from ..constants import CONTRACT_VERSION, SERVICE_NAME
from ..dependencies import AppContainer, get_container
from ..schemas.api import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(container: AppContainer = Depends(get_container)) -> HealthResponse:
    rag_loaded = container.snippet_store.loaded
    safety_loaded = container.unsafe_store.loaded
    chat_store_ready = container.chat_store.ready
    return HealthResponse(
        status="ok" if rag_loaded and safety_loaded and chat_store_ready else "degraded",
        service=SERVICE_NAME,
        contract_version=CONTRACT_VERSION,
        rag_loaded=rag_loaded,
        safety_loaded=safety_loaded,
        chat_store_ready=chat_store_ready,
    )
