"""Ray cluster connector: nodes with runtime ``ray:<connection>`` run as Ray tasks on this cluster.

Testing a connection starts a short-lived Python process that connects and reads the cluster's resources, so the
API server itself never joins a Ray cluster.
"""
from __future__ import annotations

import json
import subprocess
import sys

from pydantic import BaseModel

from athena.sdk.connector import ConnectorBase, Resource, TestResult, connector
from athena.sdk.node import ui

_PROBE = """
import json, sys, ray
kw = json.loads(sys.argv[1])
ray.init(log_to_driver=False, **kw)
res = ray.cluster_resources()
print("ATHENA_RAY " + json.dumps({"cpu": res.get("CPU", 0), "gpu": res.get("GPU", 0), "memory_gb": res.get("memory", 0) / 1024**3,
                                  "nodes": len([n for n in ray.nodes() if n.get("Alive")]), "version": ray.__version__}))
"""


class RayConfig(BaseModel):
    address: str = "ray://127.0.0.1:10001"
    namespace: str = "athena"
    ship_athena: bool = True
    pip: str = ""


@connector(
    "ray", label="Ray cluster", category="compute",
    description="Run nodes on a Ray cluster: set a node's Runs on to this connection. Its CPU, GPU and memory "
                "requests become Ray resources, and n_jobs work (forests, searches) spreads over the cluster.",
    library="Ray", license="Apache-2.0 (Ray)",
    fields={
        "address": ui("Address", help="ray://head-node:10001 (Ray Client), or auto / 127.0.0.1:6379 for a cluster on this machine (`ray start --head`)"),
        "namespace": ui("Namespace", help="Ray namespace for Athena's tasks"),
        "ship_athena": ui("Send Athena's code with each task", help="For clusters without Athena installed (ray:// only); they still need the ML libraries"),
        "pip": ui("Extra pip packages", help="Comma-separated, installed in the task's environment, e.g. scikit-learn==1.8.0, xgboost"),
    },
    extras={"Ray": "pip install 'athena-backend[ray]'"},
)
class RayConnector(ConnectorBase):
    Config = RayConfig

    def test(self, cfg: RayConfig) -> TestResult:
        from athena.runtime.adapters import RAY_HINT, ray_installed
        if not ray_installed():
            return TestResult(False, RAY_HINT)
        kw = {"address": cfg.address, "namespace": cfg.namespace or None}
        try:
            done = subprocess.run([sys.executable, "-c", _PROBE, json.dumps(kw)], capture_output=True, text=True, timeout=90, check=False)
        except subprocess.TimeoutExpired:
            return TestResult(False, f"No answer from {cfg.address} within 90 s")
        line = next((ln for ln in done.stdout.splitlines() if ln.startswith("ATHENA_RAY ")), None)
        if done.returncode != 0 or line is None:
            err = [ln for ln in (done.stderr or "").splitlines() if ln.strip()]
            return TestResult(False, f"Couldn't connect to {cfg.address}: {err[-1] if err else 'no output'}")
        info = json.loads(line.removeprefix("ATHENA_RAY "))
        return TestResult(True, f"Connected: Ray {info['version']}, {info['nodes']} node(s), {info['cpu']:g} CPU, "
                                f"{info['gpu']:g} GPU, {info['memory_gb']:.1f} GB memory", info)

    def list(self, cfg: RayConfig, path: str | None = None) -> list[Resource]:
        return []
