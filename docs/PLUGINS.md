# Writing Athena plugins

A plugin is an ordinary Python package that adds **nodes** (things you drag onto the canvas) and/or **connectors** (systems Athena can talk to). Install it into the same environment as Athena, restart, and its nodes appear in the library. You never edit Athena's code or the frontend.

## 1. Declare entry points

```toml
# pyproject.toml of your package
[project]
name = "athena-plugin-example"
dependencies = ["athena-backend"]

[project.entry-points."athena.nodes"]
example = "athena_plugin_example.nodes"           # importing this module registers your @node classes

[project.entry-points."athena.connectors"]
example = "athena_plugin_example.connectors"      # importing this module registers your @connector classes
```

`GET /api/plugins` lists every plugin Athena found, what it registered, and the error if it failed to import. A broken plugin is skipped; it never stops Athena.

## 2. A node

```python
from pydantic import BaseModel
from typing import Literal
from athena.core.handler import ExecutionContext, HandlerResult
from athena.core.registry import register_category
from athena.sdk import Port, node, ui

register_category("community", "Community")          # only if you need a new library section

@node(
    "winsorize", label="Winsorize", category="community",
    description="Clip a column to its percentiles",
    inputs=[Port("dataset", "dataset")], outputs=[Port("dataset", "dataset")],
    fields={"col": ui("Column"), "pct": ui("Percentile", min=0, max=0.5, step=0.01)},
    code=lambda v: (                                   # the exported Python for this node
        f"lo, hi = {v['in_dataset']}[{v['col']!r}].quantile([{v['pct']}, 1 - {v['pct']}])
"
        f"{v['out_dataset']} = {v['in_dataset']}.assign(**{{{v['col']!r}: {v['in_dataset']}[{v['col']!r}].clip(lo, hi)}})
"
    ),
)
class Winsorize:
    class Config(BaseModel):
        col: str = "value"
        pct: float = 0.05
        method: Literal["clip", "drop"] = "clip"       # Literal -> a select with these options

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        ctx.logger.info("Winsorizing", col=cfg.col)    # appears in the node's Logs tab
        df = ctx.inputs[0].copy()
        lo, hi = df[cfg.col].quantile([cfg.pct, 1 - cfg.pct])
        df[cfg.col] = df[cfg.col].clip(lo, hi)
        return HandlerResult(outputs=[df])
```

Rules (checked by `tests/test_node_specs.py` for built-ins; run the same checks on yours):

- **Ports** are typed strings. Connections are allowed between equal types, and between `dataset` and the split types (`X_train`, `y_test`, …). You may introduce new types.
- **Config** is a Pydantic model. `Literal[...]` becomes a select, `bool` a toggle, `int`/`float` a number, `SecretStr` a password field. Use `ui(...)` for labels, help text and special widgets (`textarea`, `file`, `connection`, `resource`).
- **Export:** give `code=`, a function (or a `str.format` template) that receives `in_<port>` and `out_<port>` (the variable names of the connected inputs and of your outputs), `id`, `var`, `label` and your config fields, and returns the code. Put imports on their own lines at column 0: they are moved to the top of the script and de-duplicated. Or give `export_note="why this can't be exported"`. One of them is required.
- **Handlers run in a worker process**, never in the API server. Return outputs in port order. Check `ctx.cancelled()` in long loops. Raise `ValueError` with a clear message for user errors.

## 3. A connector

```python
from pydantic import BaseModel, SecretStr
from athena.sdk import ConnectorBase, Resource, TestResult, connector, ui

@connector(
    "my_api", label="My API", category="api",
    description="Reads records from My API",
    library="httpx", license="Apache-2.0 (this plugin); BSD-3-Clause (httpx)",
    fields={"token": ui("API token", help="Stored in your OS keychain, or env://VAR")},
)
class MyApi(ConnectorBase):
    class Config(BaseModel):
        base_url: str = "https://api.example.com"
        token: SecretStr = SecretStr("")              # SecretStr = stored in the keychain, never in files

    def test(self, cfg) -> TestResult: ...
    def list(self, cfg, path=None) -> list[Resource]: ...
    def read(self, cfg, query, limit=None): ...        # returns a pandas DataFrame
```

Users create connections in the **Connections** dialog. A node takes a connection with `ui("Connection", widget="connection", connector="my_api")` (or a comma-separated list of connector types, e.g. `connector="my_api,other_api"`) and resolves it in the worker with `athena.connectors.store.resolve_connection(name)`, which returns `(connector, config with secrets)`. A sibling field with `ui("Table", widget="resource", connection_field="connection")` becomes a dropdown of what the chosen connection's `list()` returns.

- Secret fields are write-only: the UI never receives them back, and they never appear in `.athena` files or exported code. Exported code should read credentials from environment variables (see the SQL Query node).
- Connector categories: `database`, `warehouse`, `storage`, `api`, `tracking`, `model_provider`, `vector_store`.
- **Licenses:** set `library` and `license` honestly, including the license of the library or service you wrap. Paid services are fine as long as users bring their own credentials.
