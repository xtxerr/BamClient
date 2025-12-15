from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional

@dataclass(frozen=True)
class ApiErrorDetails:
    status: Optional[int] = None
    code: Optional[str] = None
    reason: Optional[str] = None
    message: Optional[str] = None
    detail: Any = None
    url: Optional[str] = None
    method: Optional[str] = None

class ApiError(RuntimeError):
    def __init__(self, msg: str, *, details: Optional[ApiErrorDetails] = None) -> None:
        super().__init__(msg)
        self.details = details or ApiErrorDetails()

class BadRequestError(ApiError):
    pass

class NotFoundError(ApiError):
    pass

class ConflictError(ApiError):
    pass

def map_http_error(
    *,
    status: int,
    code: str | None,
) -> type[ApiError]:
    if status == 404 or (code and "NotFound" in code):
        return NotFoundError
    if status == 409 or (code and "AlreadyExists" in code):
        return ConflictError
    if status == 400:
        return BadRequestError
    return ApiError

