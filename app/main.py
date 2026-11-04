"""Сборка приложения: REST API мини-приложения и чат-бот MAX в одном процессе.

Контракт API — ``openapi.yaml``. Сгенерированная спецификация доступна по
``/openapi.json`` и приводится к тому же виду: пути относительны к ``/api/v1``.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from . import db
from .config import Settings
from .deps import ApiException
from .routers import auth, events, planning, profile, tasks
from .security import SecurityError

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def _http_detail(exc: HTTPException) -> tuple[int, str, str]:
    status = exc.status_code
    detail = exc.detail if isinstance(exc.detail, str) else "Ошибка запроса"
    if status == 404:
        return status, "not_found", "Ресурс не найден"
    if status == 405:
        return status, "method_not_allowed", "Метод не поддерживается"
    return status, "error", detail


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.db = await db.open_db(settings.database_path)
        app.state.stop = asyncio.Event()
        app.state.background: list[asyncio.Task] = []

        if settings.bot_enabled:
            try:
                from max_bot import Bot, Dispatcher, run_polling

                from .bot import register_handlers, run_notifier

                bot = Bot(token=settings.bot_token)
                dispatcher = Dispatcher(bot)
                register_handlers(dispatcher, settings)
                app.state.bot = bot
                app.state.background.append(
                    asyncio.create_task(run_polling(bot, dispatcher))
                )
                if settings.enable_notifier:
                    app.state.background.append(
                        asyncio.create_task(
                            run_notifier(
                                bot, app.state.db, settings, app.state.stop
                            )
                        )
                    )
                logger.info("Бот MAX запущен (long polling)")
            except Exception:  # noqa: BLE001 - API должен работать и без бота
                logger.exception("Бот не запущен, API продолжает работать")
        else:
            logger.warning(
                "MAX_BOT_TOKEN не задан — бот и уведомления отключены, работает только API"
            )

        yield

        app.state.stop.set()
        for task in app.state.background:
            task.cancel()
        for task in app.state.background:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await app.state.db.close()

    app = FastAPI(
        title="TimeBalance API",
        version="0.1.0",
        description=(
            "Бэкенд мини-приложения TimeBalance в MAX. "
            "Контракт: openapi.yaml."
        ),
        lifespan=lifespan,
    )

    @app.exception_handler(ApiException)
    async def _api_exception(request, exc: ApiException):
        return JSONResponse(status_code=exc.status, content=exc.to_body())

    @app.exception_handler(SecurityError)
    async def _security_exception(request, exc: SecurityError):
        return JSONResponse(
            status_code=401, content={"code": exc.code, "message": exc.message}
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception(request, exc: RequestValidationError):
        details = {"errors": exc.errors()}
        # Pydantic кладёт в 'ctx' объекты, не сериализующиеся в JSON напрямую.
        for error in details["errors"]:
            error.pop("ctx", None)
            error.pop("input", None)
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Ошибка входных данных",
                "details": details,
            },
        )

    @app.exception_handler(HTTPException)
    async def _http_exception(request, exc: HTTPException):
        status, code, message = _http_detail(exc)
        return JSONResponse(status_code=status, content={"code": code, "message": message})

    for router in (auth.router, profile.router, events.router, tasks.router, planning.router):
        app.include_router(router, prefix=API_PREFIX)

    @app.get("/health", tags=["Service"])
    async def health():
        return {"status": "ok", "version": app.version}

    _align_openapi_with_contract(app)
    return app


def _align_openapi_with_contract(app: FastAPI) -> None:
    """Пути спецификации — относительно сервера /api/v1, как в openapi.yaml."""
    original_openapi = app.openapi

    def openapi_spec():
        if app.openapi_schema is not None:
            return app.openapi_schema
        spec = original_openapi()
        shifted = {}
        for path, definition in spec.get("paths", {}).items():
            key = path[len(API_PREFIX):] if path.startswith(API_PREFIX) else path
            shifted[key or "/"] = definition
        spec["paths"] = shifted
        spec["servers"] = [{"url": API_PREFIX}]
        app.openapi_schema = spec
        return spec

    app.openapi = openapi_spec


def route_paths(app: FastAPI) -> list[str]:
    """Полные пути роутов — используется в тестах."""
    return sorted(
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
    )


def run() -> None:
    """Точка входа: ``python code.py``."""
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


app = create_app()
