"""The entrypoint of an Athena node's Kubernetes pod.

    python -m athena.runtime.k8s_entry <payload url> <outcome url>

Reads the node's payload (type, config, inputs, …) from the artifact store, runs the handler and writes
``(result, log lines, error)`` back, all with fsspec, so the pod needs read/write access to the artifact store
(cluster identity, or credentials from the Secret named in the connection). Kept free of Kubernetes imports.
"""
from __future__ import annotations

import pickle
import socket
import sys
import tempfile


def main(payload_url: str, outcome_url: str) -> int:
    import fsspec

    from athena.runtime import remote
    with fsspec.open(payload_url, "rb") as fh:
        p = pickle.load(fh)
    outcome = remote.execute(p["node_type"], p["config"], p["inputs"], p["run_id"], p["node_id"], tempfile.gettempdir(),
                             f"Kubernetes pod {socket.gethostname()}")
    with fsspec.open(outcome_url, "wb") as fh:
        pickle.dump(outcome, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
