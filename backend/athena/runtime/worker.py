"""Worker process entry point: one process per run, so user code never runs in the API server.

A worker starts as a warm standby (imports pandas, scikit-learn and every node up front), waits for
exactly one job, runs it with the engine, and exits. A fresh process per run means no state leaks
between runs, and the supervisor can kill a hung or runaway run without touching the server.
"""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any


def worker_main(job_q: Any, events: Any, cancel_evt: Any) -> None:
    """``events`` is the send end of a Pipe: send() writes straight to the OS pipe, so an event is
    delivered even if user code kills the process right after (a Queue's feeder thread would lose it)."""
    from athena.plugins import load_plugins
    from athena.utils.tracing import utf8_output

    utf8_output()  # node logs may contain any character; a legacy Windows code page would crash on them
    load_plugins()  # built-in + plugin nodes; the slow part, done while on standby
    from athena.config import settings
    from athena.runtime.engine import run_spec
    from athena.schemas.pipeline import PipelineSpec

    events.send({"type": "_ready"})
    job = job_q.get()
    if job is None:  # shutdown before use
        return
    try:
        settings.data_dir = Path(job["data_dir"])
        cache_dir = settings.data_dir / "cache" / job["run_id"]
        cache_dir.mkdir(parents=True, exist_ok=True)
        run_spec(
            PipelineSpec.model_validate_json(job["spec"]),
            job["run_id"],
            emit=events.send,
            cancelled=cancel_evt.is_set,
            cache_dir=cache_dir,
            start_from=job.get("start_from"),
        )
    except BaseException as exc:  # the engine itself failed: report it as a crash
        events.send({"type": "_crash", "message": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
    finally:
        events.send({"type": "_done"})
