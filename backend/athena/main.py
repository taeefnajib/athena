import shutil
from pathlib import Path

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from athena.config import settings
from athena.utils.tracing import setup_logging
from athena.api.pipelines import router as pipelines_router
from athena.api.runs import router as runs_router
from athena.api.nodes import router as nodes_router
from athena.api.ws import router as ws_router
from athena.api.files import router as files_router
from athena.api.connections import router as connections_router
from athena.api.tracking import router as tracking_router
from athena.api.subflows import router as subflows_router
from athena.core.executor import pool, reset_active_run

# Register built-in nodes/connectors and installed plugins
from athena.plugins import load_plugins

load_plugins()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    reset_active_run()
    # Create required dirs
    (settings.data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "autosave").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    settings.pipelines_dir.mkdir(parents=True, exist_ok=True)
    pool.prewarm()  # first run shouldn't wait for the worker's imports
    yield
    pool.shutdown()
    clear_cache(settings.data_dir / "cache", keep_store=settings.keep_cache)


def clear_cache(cache_dir: Path, keep_store: bool) -> None:
    """On shutdown: drop per-run folders (their run ids mean nothing after a restart) and, unless
    ATHENA_KEEP_CACHE is on, the shared store of node results too."""
    if not cache_dir.exists():
        return
    for child in cache_dir.iterdir():
        if keep_store and child.name == "store":
            continue
        try:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        except OSError as exc:  # a file still open elsewhere: leave it for the next shutdown
            structlog.get_logger().warning("cache_cleanup_failed", path=str(child), error=str(exc))


app = FastAPI(title="Athena Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipelines_router)
app.include_router(runs_router)
app.include_router(nodes_router)
app.include_router(ws_router)
app.include_router(files_router)
app.include_router(connections_router)
app.include_router(subflows_router)
app.include_router(tracking_router)


@app.get("/")
async def root():
    return {"app": "Athena", "version": "0.1.0"}
