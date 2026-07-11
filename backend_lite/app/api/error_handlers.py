from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..constants import CONTRACT_VERSION, SAFETY_NOTICE
from ..errors import AppError
from ..schemas.api import ApiErrorResponse, ErrorBody

logger = logging.getLogger(__name__)


def _response(code: str, message: str, status_code: int, details: object = None) -> JSONResponse:
    body = ApiErrorResponse(
        contract_version=CONTRACT_VERSION,
        request_id=f"req_{uuid4().hex}",
        error=ErrorBody(code=code, message=message, details=details),
        safety_notice=SAFETY_NOTICE,
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json", exclude_none=True))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return _response(exc.code, exc.message, exc.status_code, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"location": list(error.get("loc", ())), "message": error.get("msg"), "type": error.get("type")}
            for error in exc.errors()
        ]
        return _response("invalid_request", "Dữ liệu yêu cầu không hợp lệ.", 400, details)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled backend error", exc_info=exc)
        return _response("internal_error", "Backend gặp lỗi không mong đợi.", 500)
