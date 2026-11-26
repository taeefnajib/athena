"""Public SDK for defining Athena nodes (and, later, connectors and runtimes).

    from athena.sdk import node, Port, ui
    from athena.core.handler import ExecutionContext, HandlerResult

    @node("my_scaler", label="My Scaler", category="feature", description="...",
          inputs=[Port("dataset", "dataset")], outputs=[Port("dataset", "dataset")],
          export_note="Code template not written yet")
    class MyScaler:
        class Config(BaseModel):
            factor: float = 1.0
        def __call__(self, ctx: ExecutionContext) -> HandlerResult: ...
"""
from athena.sdk.node import FieldUI, NodeMeta, Port, config_defaults, config_fields, node, node_spec, ui

__all__ = ["FieldUI", "NodeMeta", "Port", "config_defaults", "config_fields", "node", "node_spec", "ui"]
