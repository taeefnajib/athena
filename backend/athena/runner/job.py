"""One runner job, in its own process: ``python -m athena.runner.job <job dir>``.

Reads ``payload.pkl``, runs the node's handler and writes ``outcome.pkl``; every log line is appended to
``log.jsonl`` as it happens, so the runner can stream it to Athena while the node runs.
"""
from __future__ import annotations

import json
import os
import pickle
import socket
import sys
from pathlib import Path


def main(job_dir: str) -> int:
    from athena.runtime import remote
    d = Path(job_dir)
    with (d / "payload.pkl").open("rb") as fh:
        p = pickle.load(fh)  # sent by an authenticated Athena (see server.py)
    with (d / "log.jsonl").open("a", encoding="utf-8") as log:
        def sink(level: str, msg: str) -> None:
            log.write(json.dumps([level, msg]) + "\n")
            log.flush()

        outcome = remote.execute(p["node_type"], p["config"], p["inputs"], p["run_id"], p["node_id"], str(d / "cache"),
                                 f"runner {socket.gethostname()}", sink=sink)
    tmp = d / "outcome.pkl.tmp"
    with tmp.open("wb") as fh:
        pickle.dump(outcome, fh)
    os.replace(tmp, d / "outcome.pkl")  # appears whole or not at all
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
