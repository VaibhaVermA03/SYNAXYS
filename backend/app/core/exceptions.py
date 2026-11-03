"""Consistent error envelope: {"error": {"code", "message"}}. No internals leak."""


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str = "Internal error", *, code: str | None = None, fields: list | None = None):
        super().__init__(message)
        self.message = message
        self.fields = fields
        if code:
            self.code = code

    def to_envelope(self) -> dict:
        env = {"error": {"code": self.code, "message": self.message}}
        if self.fields:
            env["error"]["fields"] = self.fields
        return env


class NotFound(AppError): status_code, code = 404, "not_found"
class Forbidden(AppError): status_code, code = 403, "forbidden"
class Unauthorized(AppError): status_code, code = 401, "unauthorized"
class BadRequest(AppError): status_code, code = 400, "bad_request"
class Conflict(AppError): status_code, code = 409, "conflict"
class RateLimited(AppError): status_code, code = 429, "rate_limited"
class NotConfigured(AppError): status_code, code = 503, "not_configured"
class ValidationFailed(AppError): status_code, code = 422, "validation_error"
class UpstreamError(AppError): status_code, code = 502, "upstream_error"


def register_handlers(app) -> None:
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    import logging
    log = logging.getLogger("synaxys.errors")

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(exc.to_envelope(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        fields = [{"loc": [str(x) for x in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse({"error": {"code": "validation_error", "message": "Invalid request", "fields": fields}}, status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")  # full detail in logs only
        return JSONResponse({"error": {"code": "internal_error", "message": "Internal error"}}, status_code=500)
