import sys

import structlog


def utf8_output() -> None:
    """Log lines may contain any character (a check mark, a column named "São Paulo"). Windows consoles and pipes
    default to a legacy code page that can't encode them, which would turn a log call into a crash: write UTF-8 and
    replace anything unencodable instead."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # a stream that can't be reconfigured (already detached): leave it
                pass


def setup_logging() -> None:
    utf8_output()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
