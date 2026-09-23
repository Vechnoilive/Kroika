"""Stable user-facing errors without tracebacks or echoed request values."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kroika_contracts.contract_io import ContractValidationError
from kroika_contracts.ports import AIProviderError, ProviderErrorCode
from kroika_contracts.semantic import SemanticContractError


class AppError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message_ru: str,
        issues: list[dict[str, Any]] | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message_ru = message_ru
        self.issues = issues or []
        super().__init__(message_ru)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


def _response(request: Request, status: int, code: str, message: str,
              issues: list[dict[str, Any]] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message_ru": message,
            "issues": issues or [],
            "request_id": _request_id(request),
        },
        headers={"X-Request-ID": _request_id(request)},
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _response(request, exc.status_code, exc.code, exc.message_ru, exc.issues)

    @app.exception_handler(ContractValidationError)
    async def handle_contract_error(request: Request, exc: ContractValidationError) -> JSONResponse:
        issues = []
        for error in exc.errors:
            pointer, _, _detail = error.partition(": ")
            issues.append({
                "code": "CONTRACT_FIELD_INVALID",
                "severity": "blocking_error",
                "message_ru": "Поле отсутствует или имеет неверный формат.",
                "json_pointer": pointer if pointer.startswith("/") else "/",
            })
        return _response(
            request, 422, "CONTRACT_VALIDATION_FAILED",
            "Проверьте отмеченные поля и попробуйте ещё раз.", issues,
        )

    @app.exception_handler(SemanticContractError)
    async def handle_semantic_error(request: Request, exc: SemanticContractError) -> JSONResponse:
        issues = [{
            "code": issue.code,
            "severity": "blocking_error",
            "message_ru": issue.message_ru,
            "json_pointer": issue.json_pointer,
        } for issue in exc.issues]
        return _response(
            request, 422, "SEMANTIC_VALIDATION_FAILED",
            "Некоторые значения противоречат друг другу.", issues,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_http_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        issues = []
        for error in exc.errors():
            location = [str(item) for item in error.get("loc", ()) if item not in {"body", "path"}]
            pointer = "/" + "/".join(location) if location else "/"
            issues.append({
                "code": "HTTP_FIELD_INVALID",
                "severity": "blocking_error",
                "message_ru": "Проверьте обязательное поле запроса.",
                "json_pointer": pointer,
            })
        return _response(
            request, 422, "REQUEST_VALIDATION_FAILED",
            "Запрос заполнен не полностью или содержит неверное значение.", issues,
        )

    @app.exception_handler(AIProviderError)
    async def handle_provider_error(request: Request, exc: AIProviderError) -> JSONResponse:
        status = {
            ProviderErrorCode.INVALID_IMAGE: 422,
            ProviderErrorCode.INVALID_SCHEMA: 422,
            ProviderErrorCode.PAYMENT_REQUIRED: 402,
            ProviderErrorCode.RATE_LIMIT: 429,
            ProviderErrorCode.TIMEOUT: 504,
        }.get(exc.code, 503)
        return _response(request, status, exc.code.value.upper(), exc.message_ru)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        request.app.state.logger.exception(
            "unhandled_error", extra={"request_id": _request_id(request)}
        )
        return _response(
            request, 500, "INTERNAL_ERROR",
            "Не удалось выполнить действие. Данные сохранены — попробуйте ещё раз.",
        )
