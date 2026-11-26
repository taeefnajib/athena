"""Experiment tracking and model registry (MLflow).

Importing this package registers the ``mlflow`` connector, the run observer and the registry nodes.
MLflow itself is imported lazily, only when a pipeline uses it, so Athena works without the extra.
"""
from athena.tracking import connector, nodes, observer  # noqa: F401
