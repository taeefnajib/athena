"""Athena runner: a small server on another machine that runs nodes for Athena (runtime ``runner:<connection>``).

Start it with ``athena-runner`` (or ``python -m athena.runner``) on the machine that should do the work; see
``athena/runner/server.py`` for the protocol and ``athena/runtime/runner_runtime.py`` for Athena's side.
"""
