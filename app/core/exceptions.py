"""Custom HTTP exceptions and global exception handlers."""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.base_schemas import ErrorDetail, ErrorResponse


class AppException(Exception):
    """Base application exception carrying an HTTP status code and message."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    message: str = "An error occurred"

    def __init__(self, message: str | None = None) -> None:
        if message is not None:
            self.message = message
        super().__init__(self.message)


class NotFoundError(AppException):
    """Raised when a requested resource does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    message = "Resource not found"


class ConflictError(AppException):
    """Raised when a request conflicts with existing state (e.g. duplicates)."""

    status_code = status.HTTP_409_CONFLICT
    message = "Resource conflict"


class UnauthorizedError(AppException):
    """Raised when authentication is missing or invalid."""

    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Not authenticated"


class ForbiddenError(AppException):
    """Raised when the caller lacks permission for the action."""

    status_code = status.HTTP_403_FORBIDDEN
    message = "Permission denied"


class BadRequestError(AppException):
    """Raised for invalid input that is not a schema validation error."""

    status_code = status.HTTP_400_BAD_REQUEST
    message = "Bad request"


class UnprocessableEntityError(AppException):
    """Raised when a semantically-invalid request cannot be processed (422)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "Unprocessable entity"


class TooManyRequestsError(AppException):
    """Raised when a caller exceeds an application-level rate quota (429)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Too many requests. Please try again later."


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers producing a consistent error envelope."""

    @app.exception_handler(AppException)
    async def _app_exception_handler(
        _request: Request, exc: AppException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(message=exc.message).model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(message=str(exc.detail)).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            ErrorDetail(
                field=".".join(str(p) for p in err.get("loc", [])[1:]) or None,
                message=err.get("msg", "Invalid value"),
            )
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                message="Validation error", errors=errors
            ).model_dump(),
        )
