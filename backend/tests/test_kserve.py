"""KServe deployments: the InferenceService manifest, applying it through a stand-in cluster API, the V1 protocol
the bundle's service answers, and pushing images."""
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from athena.config import settings
from athena.connectors import kubernetes as kube
from athena.connectors import store
from athena.main import app
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec, Resources
from athena.serving import builds, endpoints, kserve
from athena.serving.bundle import bundle_from_run

client = TestClient(app)
BACKEND = Path(__file__).parents[1]


class ApiError(Exception):
    def __init__(self, status: int, reason: str = "") -> None:
        super().__init__(reason or str(status))
        self.status, self.reason = status, reason


class FakeCustomObjects:
    """CustomObjectsApi for InferenceServices, kept in a dict."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.installed = True
        self.version = 0

    def create_namespaced_custom_object(self, group, version, namespace, plural, body):
        assert (group, version, plural) == ("serving.kserve.io", "v1beta1", "inferenceservices")
        if not self.installed:
            raise ApiError(404, "Not Found")
        key = (namespace, body["metadata"]["name"])
        if key in self.objects:
            raise ApiError(409, "AlreadyExists")
        self.version += 1
        self.objects[key] = {**body, "metadata": {**body["metadata"], "resourceVersion": str(self.version)}}

    def get_namespaced_custom_object(self, group, version, namespace, plural, name):
        if (namespace, name) not in self.objects:
            raise ApiError(404, "Not Found")
        return self.objects[(namespace, name)]

    def replace_namespaced_custom_object(self, group, version, namespace, plural, name, body):
        assert body["metadata"]["resourceVersion"] == self.objects[(namespace, name)]["metadata"]["resourceVersion"]
        self.version += 1
        self.objects[(namespace, name)] = {**body, "metadata": {**body["metadata"], "resourceVersion": str(self.version)}}

    def delete_namespaced_custom_object(self, group, version, namespace, plural, name):
        if self.objects.pop((namespace, name), None) is None:
            raise ApiError(404, "Not Found")

    def become_ready(self, namespace, name):
        obj = self.objects[(namespace, name)]
        obj["status"] = {"url": f"http://{name}.{namespace}.example.com",
                         "conditions": [{"type": "PredictorReady", "status": "True"}, {"type": "Ready", "status": "True"}]}


def _n(nid, ntype, **config):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "config": config}


def _e(eid, s, t, sp=0, tp=0):
    return {"id": eid, "source": s, "target": t, "source_port": sp, "target_port": tp}


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    spec = PipelineSpec.model_validate({"name": "churn", "nodes": [
        _n("csv", "csv_loader", path=str(BACKEND / "data.csv")), _n("imp", "imputer", strategy="median"), _n("tt", "train_test"),
        _n("rf", "rf", n_estimators=15)], "edges": [_e("a", "csv", "imp"), _e("b", "imp", "tt"), _e("c", "tt", "rf", 0, 0), _e("d", "tt", "rf", 1, 1)]})
    run_id = str(uuid.uuid4())
    assert run_spec(spec, run_id, lambda e: None, lambda: False, tmp_path / "cache" / run_id) == "completed"
    b = bundle_from_run("Churn Model", spec, run_id, "rf", 0)
    yield b
    endpoints.stop_all()
    builds.stop_all()


@pytest.fixture
def cluster(bundle, monkeypatch):
    fake = FakeCustomObjects()
    monkeypatch.setattr(kube, "custom_objects", lambda cfg: fake)
    store.save_connection("prod", "kubernetes", {"namespace": "models", "image_pull_secret": "ghcr"})
    return fake


def test_manifest():
    m = kserve.manifest("churn-model", "ghcr.io/me/churn-model:3", "models", 1, 3, Resources(cpu=1, memory_gb=2), "sa", "ghcr")
    p = m["spec"]["predictor"]
    c = p["containers"][0]
    assert m["kind"] == "InferenceService" and m["metadata"] == {"name": "churn-model", "namespace": "models",
                                                                  "labels": {"app.kubernetes.io/managed-by": "athena", "athena/model": "churn-model"}}
    assert c["image"] == "ghcr.io/me/churn-model:3" and c["ports"] == [{"containerPort": 8000, "protocol": "TCP"}]
    assert c["readinessProbe"]["httpGet"] == {"path": "/health", "port": 8000}
    assert c["resources"] == {"requests": {"cpu": "1", "memory": "2048Mi"}, "limits": {"memory": "2048Mi"}}
    assert (p["minReplicas"], p["maxReplicas"], p["serviceAccountName"], p["imagePullSecrets"]) == (1, 3, "sa", [{"name": "ghcr"}])
    assert yaml.safe_load(kserve.to_yaml(m)) == m
    assert kserve.isvc_name("9-Lives Model!") == "m-9-lives-model" and len(kserve.isvc_name("x" * 90)) <= 40
    with pytest.raises(kserve.KServeError, match="Choose the image"):
        kserve.manifest("x", "", "default")


def test_deploy_status_and_delete(cluster: FakeCustomObjects, bundle: dict):
    slug = bundle["slug"]
    res = client.post(f"/api/serving/bundles/{slug}/kserve", json={"connection": "prod", "image": "ghcr.io/me/churn-model:1",
                                                                  "min_replicas": 0, "max_replicas": 2, "resources": {"cpu": 1}})
    assert res.status_code == 200, res.text
    st = res.json()
    assert st["deployed"] and not st["ready"] and st["namespace"] == "models" and st["name"] == "churn-model"
    obj = cluster.objects[("models", "churn-model")]
    assert obj["spec"]["predictor"]["minReplicas"] == 0 and obj["spec"]["predictor"]["imagePullSecrets"] == [{"name": "ghcr"}]

    again = client.post(f"/api/serving/bundles/{slug}/kserve", json={"connection": "prod", "image": "ghcr.io/me/churn-model:2"})
    assert again.status_code == 200  # an existing InferenceService is replaced
    assert cluster.objects[("models", "churn-model")]["spec"]["predictor"]["containers"][0]["image"] == "ghcr.io/me/churn-model:2"

    cluster.become_ready("models", "churn-model")
    st = client.get(f"/api/serving/bundles/{slug}/kserve").json()
    assert st["ready"] and st["predict_url"] == "http://churn-model.models.example.com/v1/models/churn-model:predict"
    assert client.get("/api/serving/bundles").json()["bundles"][0]["kserve"]["image"] == "ghcr.io/me/churn-model:2"

    assert client.delete(f"/api/serving/bundles/{slug}/kserve").status_code == 200
    assert cluster.objects == {} and client.get(f"/api/serving/bundles/{slug}/kserve").json() == {"deployed": False}


def test_errors_are_explained(cluster: FakeCustomObjects, bundle: dict):
    slug = bundle["slug"]
    cluster.installed = False
    res = client.post(f"/api/serving/bundles/{slug}/kserve", json={"connection": "prod", "image": "ghcr.io/me/m:1"})
    assert res.status_code == 400 and "KServe isn't installed" in res.json()["detail"]["detail"]
    cluster.installed = True
    res = client.post(f"/api/serving/bundles/{slug}/kserve", json={"connection": "prod"})  # no image built yet
    assert "Choose the image" in res.json()["detail"]["detail"]
    store.save_connection("db", "sql", {"url": "sqlite:///x.db"})
    res = client.post(f"/api/serving/bundles/{slug}/kserve", json={"connection": "db", "image": "a/b:1"})
    assert "isn't a Kubernetes cluster connection" in res.json()["detail"]["detail"]

    client.post(f"/api/serving/bundles/{slug}/kserve", json={"connection": "prod", "image": "ghcr.io/me/m:1"})
    cluster.objects.clear()  # deleted with kubectl behind Athena's back
    st = client.get(f"/api/serving/bundles/{slug}/kserve").json()
    assert not st["deployed"] and "no longer exists" in st["message"]


def test_manifest_download_uses_the_last_image(bundle: dict):
    slug = bundle["slug"]
    (Path(bundle["path"]) / "build.json").write_text(json.dumps({"target": "push", "state": "succeeded", "tag": "ghcr.io/me/churn-model:7"}))
    res = client.get(f"/api/serving/bundles/{slug}/kserve/manifest", params={"namespace": "ml"})
    assert res.status_code == 200 and "attachment" in res.headers["content-disposition"]
    m = yaml.safe_load(res.text)
    assert m["spec"]["predictor"]["containers"][0]["image"] == "ghcr.io/me/churn-model:7" and m["metadata"]["namespace"] == "ml"
    store.save_connection("prod", "kubernetes", {"namespace": "models", "service_account": "kserve-sa"})
    m = yaml.safe_load(client.get(f"/api/serving/bundles/{slug}/kserve/manifest", params={"connection": "prod"}).text)
    assert m["metadata"]["namespace"] == "models" and m["spec"]["predictor"]["serviceAccountName"] == "kserve-sa"  # read, never contacted


def test_service_answers_the_kserve_v1_protocol(bundle: dict):
    slug = bundle["slug"]
    assert client.post(f"/api/serving/endpoints/{slug}").json()["running"]
    url = endpoints.status(slug)["url"]
    example = json.loads((Path(bundle["path"]) / "example.json").read_text())["rows"]

    def post(path: str, body: dict) -> dict:
        req = urllib.request.Request(url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    plain = post("/predict", {"rows": example * 2})
    v1 = post(f"/v1/models/{slug}:predict", {"instances": example * 2})
    as_lists = post(f"/v1/models/{slug}:predict", {"instances": [list(example[0].values())]})
    assert v1 == plain and as_lists["predictions"] == plain["predictions"][:1]
    with urllib.request.urlopen(f"{url}/v1/models/{slug}", timeout=10) as r:
        assert json.loads(r.read())["ready"] is True
    metrics = urllib.request.urlopen(f"{url}/metrics", timeout=10).read().decode()
    assert 'athena_requests_total{status="200"} 3' in metrics  # V1 calls are measured too


def test_push(bundle: dict, tmp_path: Path, monkeypatch):
    tool = tmp_path / "fake_docker.py"
    tool.write_text("import sys; print('fake docker', *sys.argv[1:])", encoding="utf-8")
    monkeypatch.setattr(builds, "TOOL_OVERRIDES", {"docker": [sys.executable, str(tool)]})
    slug = bundle["slug"]
    res = client.post(f"/api/serving/bundles/{slug}/build", json={"target": "push"})
    assert res.status_code == 400 and "Build the Docker image first" in res.json()["detail"]["detail"]
    res = client.post(f"/api/serving/bundles/{slug}/build", json={"target": "docker", "image": "--rm"})
    assert res.status_code == 400 and "isn't a valid image name" in res.json()["detail"]["detail"]

    def wait() -> dict:
        for _ in range(100):
            st = builds.status(slug)
            if st and st["state"] != "running":
                return st
            time.sleep(0.1)
        raise AssertionError("didn't finish")

    client.post(f"/api/serving/bundles/{slug}/build", json={"target": "docker", "image": "ghcr.io/me/churn-model:4"})
    assert wait()["tag"] == "ghcr.io/me/churn-model:4"
    client.post(f"/api/serving/bundles/{slug}/build", json={"target": "push"})  # pushes what was just built
    st = wait()
    assert st["state"] == "succeeded" and "fake docker push ghcr.io/me/churn-model:4" in st["log"]
    assert builds.last_image(slug) == "ghcr.io/me/churn-model:4"
