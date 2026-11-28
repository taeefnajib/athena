"""Kubernetes connector: nodes with runtime ``k8s:<connection>`` run as Kubernetes Jobs on this cluster.

Credentials come from your kubeconfig (a context in it) or, when Athena itself runs in a cluster, the pod's
service account; nothing secret is stored in the connection. Nodes hand data to their pods through an artifact
store both sides can reach: an object-storage URL (s3://, gs://, az://) or a saved storage connection.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from athena.sdk.connector import ConnectorBase, Resource, TestResult, connector
from athena.sdk.node import ui


class KubernetesConfig(BaseModel):
    context: str = ""
    kubeconfig: str = ""
    namespace: str = "default"
    image: str = ""
    artifacts: str = ""
    storage_connection: str = ""
    service_account: str = ""
    env_secret: str = ""
    image_pull_secret: str = ""
    ship_athena: bool = True


def clients(cfg: KubernetesConfig) -> tuple[Any, Any]:
    """(BatchV1Api, CoreV1Api) for the connection: the kubeconfig context, or in-cluster config."""
    from kubernetes import client, config
    if cfg.kubeconfig or cfg.context:
        api = config.new_client_from_config(config_file=cfg.kubeconfig or None, context=cfg.context or None)
    else:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        api = client.ApiClient()
    return client.BatchV1Api(api), client.CoreV1Api(api)


@connector(
    "kubernetes", label="Kubernetes cluster", category="compute",
    description="Run nodes as Kubernetes Jobs: set a node's Runs on to this connection. Its CPU, memory and GPU "
                "requests become the pod's requests and limits; inputs and outputs travel through an artifact store.",
    library="kubernetes (official Python client)", license="Apache-2.0",
    fields={
        "context": ui("kubeconfig context", help="Empty: the current context (or the in-cluster service account when Athena runs in Kubernetes)"),
        "kubeconfig": ui("kubeconfig file", help="Empty: ~/.kube/config or $KUBECONFIG"),
        "namespace": ui("Namespace"),
        "image": ui("Container image", help="Python with the libraries your nodes use (pandas, scikit-learn, fsspec + the artifact store's driver, …), or with athena-backend installed"),
        "artifacts": ui("Artifact store", help="Where node inputs and outputs are exchanged: s3://bucket/athena, gs://…, az://…, or a path inside the storage connection below"),
        "storage_connection": ui("Storage connection", help="Optional: the name of a saved storage connection Athena uses to reach the artifact store (pods use their own credentials)"),
        "service_account": ui("Service account", help="For pods that reach the artifact store through cluster identity (IRSA, Workload Identity)"),
        "env_secret": ui("Secret with environment variables", help="Name of a Kubernetes Secret loaded into the pod's environment (e.g. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY for s3://)"),
        "image_pull_secret": ui("Image pull secret", help="For a private registry"),
        "ship_athena": ui("Send Athena's code with each job", help="For images without athena-backend: its code is uploaded to the artifact store once per run"),
    },
    extras={"Kubernetes client": "pip install 'athena-backend[k8s]'"},
)
class KubernetesConnector(ConnectorBase):
    Config = KubernetesConfig

    def test(self, cfg: KubernetesConfig) -> TestResult:
        from athena.runtime.adapters import k8s_installed
        if not k8s_installed():
            from athena.runtime.adapters import K8S_HINT
            return TestResult(False, K8S_HINT)
        missing = [name for name, value in (("Container image", cfg.image), ("Artifact store", cfg.artifacts)) if not value.strip()]
        try:
            batch, core = clients(cfg)
            batch.list_namespaced_job(cfg.namespace, limit=1, _request_timeout=15)  # can we see Jobs in the namespace?
        except Exception as exc:  # noqa: BLE001 - any client error is a failed test, reported as such
            return TestResult(False, f"Couldn't reach the cluster: {str(exc).splitlines()[0][:200]}")
        message = f"Connected: Jobs visible in namespace {cfg.namespace!r}"
        details: dict[str, Any] = {}
        try:  # listing nodes needs cluster-wide permission, which a namespace-scoped user may not have
            nodes = core.list_node(_request_timeout=15).items
            details = {"nodes": len(nodes), "gpus": sum(int((n.status.allocatable or {}).get("nvidia.com/gpu", 0)) for n in nodes)}
            message += f"; {details['nodes']} node(s), {details['gpus']} GPU(s)"
        except Exception:  # noqa: BLE001, S110 - optional detail
            pass
        if missing:
            return TestResult(False, message + f". Still needed: {', '.join(missing)}")
        return TestResult(True, message, details)

    def list(self, cfg: KubernetesConfig, path: str | None = None) -> list[Resource]:
        return []
