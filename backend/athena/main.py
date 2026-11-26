import shutil
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
    # Cleanup cache on shutdown
    cache_dir = settings.data_dir / "cache"
    if cache_dir.exists():
        try:
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


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


@app.get("/")
async def root():
    return {"app": "Athena", "version": "0.1.0"}
