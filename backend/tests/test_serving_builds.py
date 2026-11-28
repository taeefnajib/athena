"""Building bundles into Docker images and Bentos, with stand-in `docker` / `bentoml` commands (no real Docker)."""
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from athena.config import settings
from athena.main import app
from athena.serving import builds, endpoints

client = TestClient(app)

FAKE_TOOL = '''
import sys, time
args = sys.argv[1:]
print("fake", " ".join(args), flush=True)
if "--slow" in open("FAKE_MODE").read():
    time.sleep(60)
if "fail" in open("FAKE_MODE").read():
    print("ERROR: Cannot connect to the Docker daemon", flush=True)
    sys.exit(1)
if args[0] == "build" and "bentofile.yaml" in args:
    print('Successfully built Bento(tag="athena_model:abc123").', flush=True)
print("done", flush=True)
'''


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch):
    """A bundle folder with the files a build needs, and stand-in tools."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    path = tmp_path / "models" / "churn"
    path.mkdir(parents=True)
    for name in ("Dockerfile", "bentofile.yaml", "service.py", "model.joblib"):
        (path / name).write_text("x", encoding="utf-8")
    (path / "schema.json").write_text(json.dumps({"name": "churn", "slug": "churn", "features": [], "model": "M", "task": "classification", "version": "1"}), encoding="utf-8")
    (path / "FAKE_MODE").write_text("ok", encoding="utf-8")
    tool = tmp_path / "fake_tool.py"
    tool.write_text(FAKE_TOOL, encoding="utf-8")
    monkeypatch.setattr(builds, "TOOL_OVERRIDES", {"docker": [sys.executable, str(tool)], "bentoml": [sys.executable, str(tool)]})
    yield path
    builds.stop_all()
    endpoints.stop_all()


def _wait(slug: str) -> dict:
    for _ in range(100):
        st = builds.status(slug)
        if st and st["state"] != "running":
            return st
        time.sleep(0.1)
    raise AssertionError("build didn't finish")


def test_docker_build_succeeds_and_is_remembered(bundle: Path):
    res = client.post("/api/serving/bundles/churn/build", json={"target": "docker"})
    assert res.status_code == 200, res.text
    assert res.json()["state"] in ("running", "succeeded")
    st = _wait("churn")
    assert st["state"] == "succeeded" and st["tag"] == "churn:latest"
    assert st["run_command"] == "docker run --rm -p 8000:8000 churn:latest"
    assert st["log"][0].endswith("build -t churn:latest .") and "fake build -t churn:latest ." in st["log"]
    builds._BUILDS.clear()  # as after a restart: the last build comes from build.json
    again = client.get("/api/serving/bundles/churn/build").json()
    assert again["state"] == "succeeded" and again["tag"] == "churn:latest"
    listed = client.get("/api/serving/bundles").json()["bundles"][0]
    assert listed["build"]["state"] == "succeeded"


def test_bento_build_reads_the_tag_from_the_log(bundle: Path):
    client.post("/api/serving/bundles/churn/build", json={"target": "bento"})
    st = _wait("churn")
    assert st["state"] == "succeeded" and st["tag"] == "athena_model:abc123" and st["run_command"] == "bentoml serve athena_model:abc123"


def test_failed_build_shows_the_log(bundle: Path):
    (bundle / "FAKE_MODE").write_text("fail", encoding="utf-8")
    client.post("/api/serving/bundles/churn/build", json={"target": "docker"})
    st = _wait("churn")
    assert st["state"] == "failed" and st["tag"] == "" and st["run_command"] == ""
    assert any("Cannot connect to the Docker daemon" in line for line in st["log"])


def test_one_build_at_a_time_and_cancel(bundle: Path):
    (bundle / "FAKE_MODE").write_text("--slow", encoding="utf-8")
    assert client.post("/api/serving/bundles/churn/build", json={"target": "docker"}).json()["state"] == "running"
    busy = client.post("/api/serving/bundles/churn/build", json={"target": "bento"})
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "BUILD_RUNNING"
    assert client.delete("/api/serving/bundles/churn/build").status_code == 200
    assert builds.status("churn")["state"] == "cancelled"


def test_missing_tools_and_bad_requests(bundle: Path, monkeypatch):
    monkeypatch.setattr(builds, "TOOL_OVERRIDES", {"docker": None, "bentoml": None})
    tools = client.get("/api/serving/tools").json()
    assert tools["docker"]["available"] is False and "Docker" in tools["docker"]["hint"]
    res = client.post("/api/serving/bundles/churn/build", json={"target": "docker"})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "BUILD_UNAVAILABLE"
    assert client.post("/api/serving/bundles/churn/build", json={"target": "helm"}).status_code == 422
    assert client.post("/api/serving/bundles/nope/build", json={"target": "docker"}).status_code == 404
    assert client.get("/api/serving/bundles/churn/build").json() is None
