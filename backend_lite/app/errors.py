from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class InvalidRequestError(AppError):
    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__("invalid_request", message, 400, details)


class ChatNotFoundError(AppError):
    def __init__(self, message: str = "Không tìm thấy cuộc trò chuyện.") -> None:
        super().__init__("chat_not_found", message, 404)


class RetrievalError(AppError):
    def __init__(self, message: str = "Nguồn tham khảo tạm thời không khả dụng.") -> None:
        super().__init__("retrieval_error", message, 503)
