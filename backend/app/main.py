"""FastAPI application factory."""
import time
import uuid

import structlog
from fastapi import FastAPI, Request
from threadpoolctl import threadpool_limits
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import get_settings
from app.logging_setup import configure_logging, get_logger
from app.services import NotFoundError, UnavailableError

log = get_logger("api")


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    # Inference requests are small and run concurrently in worker threads; letting each spawn a full OpenMP pool
    # oversubscribes the CPU (measured: multi-second latency for ~0.1 s of work). Serving uses 1 native thread/request.
    threadpool_limits(limits=1)
    app = FastAPI(title="F1 Race Strategy & Lap-Time Prediction", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",")], allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def request_log(request: Request, call_next):  # type: ignore[no-untyped-def]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=uuid.uuid4().hex[:8])
        t0 = time.perf_counter()
        response = await call_next(request)
        log.info("request", method=request.method, path=request.url.path, status=response.status_code,
                 ms=round((time.perf_counter() - t0) * 1000, 1))
        return response

    @app.exception_handler(NotFoundError)
    async def _nf(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"error": "not_found", "detail": str(exc)}, status_code=404)

    @app.exception_handler(UnavailableError)
    async def _un(_: Request, exc: UnavailableError) -> JSONResponse:
        return JSONResponse({"error": "unavailable", "detail": str(exc)}, status_code=503)

    @app.exception_handler(Exception)
    async def _any(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled", error=repr(exc))
        return JSONResponse({"error": "internal_error", "detail": "unexpected server error"}, status_code=500)

    app.include_router(router)
    return app


app = create_app()
