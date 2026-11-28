"""Athena runner connector: nodes with runtime ``runner:<connection>`` run on the machine serving ``athena-runner``."""
from __future__ import annotations

from pydantic import BaseModel, SecretStr

from athena.sdk.connector import ConnectorBase, Resource, TestResult, connector
from athena.sdk.node import ui


class RunnerConfig(BaseModel):
    url: str = "http://127.0.0.1:8765"
    token: SecretStr = SecretStr("")
    verify_tls: bool = True


@connector(
    "runner", label="Athena runner", category="compute",
    description="Run nodes on another machine (a GPU box, a server next to the data) that runs athena-runner. "
                "Set a node's Runs on to this connection; its logs stream back while it runs.",
    library="Athena", license="(built in)",
    fields={
        "url": ui("Runner URL", help="http://127.0.0.1:8765 through an SSH tunnel (ssh -L 8765:127.0.0.1:8765 you@machine), or https://… behind TLS"),
        "token": ui("Token", help="The token athena-runner printed (or ATHENA_RUNNER_TOKEN on that machine). Stored in your OS keychain, or env://VAR"),
        "verify_tls": ui("Verify the TLS certificate", help="Turn off only for a self-signed certificate you trust"),
    },
)
class RunnerConnector(ConnectorBase):
    Config = RunnerConfig

    def test(self, cfg: RunnerConfig) -> TestResult:
        from athena.runtime.runner_runtime import RunnerError, client_for
        try:
            info = client_for(cfg).json("GET", "/info")
        except RunnerError as exc:
            return TestResult(False, str(exc))
        from athena.runner.server import _version
        mine = _version()
        memory = f"{info['memory_gb']:g} GB, " if info["memory_gb"] else ""
        msg = (f"Connected: Athena {info['athena_version'] or '?'} on Python {info['python']}, {info['cpus']} CPU, "
               f"{memory}{info['gpus']} GPU, {info['max_jobs']} job slot(s)")
        if mine and info["athena_version"] and info["athena_version"] != mine:
            msg += f". Note: this Athena is {mine}; keep both on the same version so nodes behave the same"
        return TestResult(True, msg, info)

    def list(self, cfg: RunnerConfig, path: str | None = None) -> list[Resource]:
        return []
