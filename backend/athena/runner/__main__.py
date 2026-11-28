"""``athena-runner``: serve this machine as a runner for Athena.

    athena-runner                                   # 127.0.0.1:8765, prints a new token
    ATHENA_RUNNER_TOKEN=... athena-runner --host 0.0.0.0 --ssl-certfile cert.pem --ssl-keyfile key.pem

Whoever has the token can run code on this machine. Keep it on 127.0.0.1 and reach it through an SSH tunnel
(``ssh -L 8765:127.0.0.1:8765 me@gpu-box``), or put it behind TLS on a trusted network.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import secrets
import sys
import tempfile
from pathlib import Path


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="athena-runner", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 (default) keeps it on this machine; use an SSH tunnel to reach it")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=os.environ.get("ATHENA_RUNNER_TOKEN", ""),
                        help="the token Athena must send (default: $ATHENA_RUNNER_TOKEN, else a new one is printed)")
    parser.add_argument("--max-jobs", type=int, default=1, help="nodes running at once; the rest wait")
    parser.add_argument("--work-dir", default=str(Path(tempfile.gettempdir()) / "athena-runner"), help="where job files live")
    parser.add_argument("--ssl-certfile", default=None)
    parser.add_argument("--ssl-keyfile", default=None)
    args = parser.parse_args(argv)

    token = args.token
    if not token:
        if not _loopback(args.host):
            print("error: listening beyond this machine needs a token you chose: set ATHENA_RUNNER_TOKEN or pass --token", file=sys.stderr)
            return 2
        token = secrets.token_urlsafe(32)
        print(f"Runner token (paste it into Athena's runner connection): {token}", flush=True)
    if not _loopback(args.host) and not args.ssl_certfile:
        print("warning: serving without TLS beyond this machine: the token and your data travel in clear text", file=sys.stderr)

    import uvicorn

    from athena.plugins import load_plugins
    from athena.runner.server import create_app
    load_plugins()  # fail now, not on the first job, if this machine can't load Athena's nodes
    app = create_app(token, Path(args.work_dir), max(1, args.max_jobs))
    scheme = "https" if args.ssl_certfile else "http"
    print(f"Athena runner on {scheme}://{args.host}:{args.port} (up to {args.max_jobs} job(s) at once)", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning",
                ssl_certfile=args.ssl_certfile, ssl_keyfile=args.ssl_keyfile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
