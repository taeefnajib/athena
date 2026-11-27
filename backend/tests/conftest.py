import pytest
from athena.config import settings


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect ATHENA_DATA_DIR to a per-test tmp dir so tests never touch the user's
    real ~/.athena/ directory (cache, autosave, etc.)."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)


@pytest.fixture(scope="session")
def _mlflow_template_store(tmp_path_factory):
    """Creating an MLflow SQLite store runs its migrations (~20 s): do it once per session."""
    pytest.importorskip("mlflow")
    from athena.tracking.session import ensure_experiment, mlflow_session
    root = tmp_path_factory.mktemp("mlflow-template")
    old = settings.data_dir
    settings.data_dir = root
    try:
        with mlflow_session("") as dest:
            ensure_experiment(dest, "athena")
    finally:
        settings.data_dir = old
    return root / "mlflow" / "mlflow.db"


@pytest.fixture
def mlflow_local_store(_mlflow_template_store, isolated_data_dir):
    """A fresh, ready local MLflow store in this test's data dir (a copy of the session template)."""
    import shutil
    from athena.tracking.session import local_db
    local_db().parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_mlflow_template_store, local_db())
