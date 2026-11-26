"""A minimal third-party plugin, as a community package would write it."""
from pydantic import BaseModel

from athena.core.handler import ExecutionContext, HandlerResult
from athena.core.registry import register_category
from athena.sdk import Port, node, ui

register_category("community", "Community")


@node(
    "test_plugin_double", label="Double Column", category="community",
    description="Multiply a numeric column by two (plugin test fixture)",
    inputs=[Port("dataset", "dataset")], outputs=[Port("dataset", "dataset")],
    fields={"col": ui("Column")},
    code="# --- Node {id}: Double Column ---\ndf_{var} = df_{src}.assign(**{{{col!r}: df_{src}[{col!r}] * 2}})\n",
)
class DoubleColumn:
    class Config(BaseModel):
        col: str = "x"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df = ctx.inputs[0].copy()
        df[cfg.col] = df[cfg.col] * 2
        return HandlerResult(outputs=[df])
