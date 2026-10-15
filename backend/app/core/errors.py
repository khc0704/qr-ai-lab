"""Uniform error shape: {"detail": {"code": "UPPER_SNAKE", "message": "..."}}."""

from __future__ import annotations

from fastapi import HTTPException, status


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message})
        self.code = code


def bad_request(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_400_BAD_REQUEST, code, message)


def unauthorized(code: str = "UNAUTHORIZED", message: str = "需要登入") -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, code, message)


def forbidden(code: str = "FORBIDDEN", message: str = "沒有權限") -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, code, message)


def not_found(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, code, message)


def conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)
