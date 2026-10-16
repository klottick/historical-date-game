"""API-preserving release adapter; static fallback is deliberately allowlisted."""

import os
import re
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

SPA_ROUTES = {
    "/",
    "/login",
    "/recover-password",
    "/reset-password",
    "/signup",
    "/admin",
    "/daily",
    "/freeplay",
    "/items",
    "/settings",
}


def create_app(frontend_dir: Path) -> FastAPI:
    from app.main import app as api

    app = FastAPI(title=api.title, openapi_url=api.openapi_url)
    app.router.routes = list(api.router.routes)
    app.user_middleware = list(api.user_middleware)
    app.exception_handlers = dict(api.exception_handlers)

    @app.middleware("http")
    async def reject_ambiguous_paths(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        raw = request.scope.get("raw_path", b"").lower()
        if (
            any(code in raw for code in (b"%2e", b"%2f", b"%5c", b"%25"))
            or "\\" in request.url.path
        ):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return await call_next(request)

    @app.get("/healthz", include_in_schema=False)
    def readiness() -> JSONResponse:
        from app.distribution.startup import check_ready

        try:
            check_ready()
        except Exception:
            return JSONResponse(
                {"status": "unavailable"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse({"status": "ready"}, headers={"Cache-Control": "no-store"})

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        route = "/" + path
        spa = route in SPA_ROUTES
        if route.startswith("/play/"):
            try:
                spa = str(UUID(route.removeprefix("/play/"))) == route.removeprefix(
                    "/play/"
                )
            except ValueError:
                pass
        if spa:
            target = frontend_dir / "index.html"
            cache = "no-cache"
        elif path.startswith("assets/") and not any(
            part in {"", ".", ".."} for part in path.split("/")
        ):
            target = frontend_dir / path
            cache = (
                "public, max-age=31536000, immutable"
                if re.search(r"-[A-Za-z0-9_-]{8,}\.[a-z0-9]+$", path)
                else "no-cache"
            )
        else:
            raise HTTPException(404)
        if not target.is_file() or any(
            p.is_symlink() for p in (target, *target.parents)
        ):
            raise HTTPException(404)
        return FileResponse(target, headers={"Cache-Control": cache})

    return app


def release_app() -> FastAPI:
    from app.distribution.config import validate_environment

    validate_environment(os.environ)
    return create_app(Path("/app/frontend/dist"))
