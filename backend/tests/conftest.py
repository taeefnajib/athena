import pytest
from athena.config import settings


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect ATHENA_DATA_DIR to a per-test tmp dir so tests never touch the user's
    real ~/.athena/ directory (cache, autosave, etc.)."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
