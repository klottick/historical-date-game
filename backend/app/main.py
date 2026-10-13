import sentry_sdk
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.game.run_service import GameServiceError
from app.media import GameMediaFiles


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.middleware("http")
async def private_game_cache_policy(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    response = await call_next(request)
    game_prefix = f"{settings.API_V1_STR}/games/"
    if (
        request.url.path.startswith(game_prefix)
        and request.url.path != game_prefix + "options"
    ):
        # Apply after handled errors and CORS, not just successful route returns.
        response.headers["Cache-Control"] = "no-store"
        vary = {
            field.strip().lower()
            for field in response.headers.get("Vary", "").split(",")
        }
        for field in ("Cookie", "Authorization", "X-Game-Context"):
            if field.lower() not in vary:
                response.headers.add_vary_header(field)
    return response


@app.exception_handler(GameServiceError)
async def game_service_error(_request: Request, exc: GameServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code, "message": exc.message}},
    )


app.mount("/media", GameMediaFiles(settings.GAME_DATA_DIR / "media"), name="game-media")
