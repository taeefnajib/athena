"""Export templates for nodes that talk to external systems. Exported code never contains credentials:
it reads them from environment variables (or the provider's standard credential chain)."""
from __future__ import annotations

from typing import Any

from athena.nodes.export.common import Template, lines

V = dict[str, Any]


def db_connector(v: V) -> str:
    env = "ATHENA_" + "".join(c if c.isalnum() else "_" for c in (v["connection"] or "database")).upper() + "_URL"
    head = f"\n{v['out_dataset']} = {v['out_dataset']}.head({int(v['limit'])})" if v["limit"] else ""
    return lines("import os", "import pandas as pd", "from sqlalchemy import create_engine, text",
                 f"# Set {env} to the database's SQLAlchemy URL (connection {v['connection']!r}).",
                 f"with create_engine(os.environ[{env!r}]).connect() as _conn:",
                 f"    {v['out_dataset']} = pd.read_sql_query(text({v['query']!r}), _conn){head}")


def duckdb_sql(v: V) -> str:
    regs = [f"in1 = {v['in_in1']}" if v["in_in1"] != "None" else "", f"in2 = {v['in_in2']}" if v["in_in2"] != "None" else ""]
    return lines("import duckdb", *regs, f"{v['out_dataset']} = duckdb.sql({v['query']!r}).df()")


def storage_loader(v: V) -> str:
    out = v["out_dataset"]
    try:
        from athena.connectors.storage import StorageConfig, detect_format, url
        from athena.connectors.store import get_connection
        cfg = StorageConfig(**get_connection(v["connection"])["config"])
    except Exception:
        return lines("import pandas as pd", f"# Connection {v['connection']!r} isn't saved on this machine: set the file URL here.",
                     f"{out} = pd.read_parquet('s3://bucket/{v['path']}')")
    target = url(cfg, v["path"])
    kind = detect_format(target, v["format"]) or "parquet"
    opts: dict[str, Any] = {}
    if cfg.protocol == "s3" and cfg.endpoint_url:
        opts["client_kwargs"] = {"endpoint_url": cfg.endpoint_url}
    if cfg.protocol == "azure" and cfg.azure_account_name:
        opts["account_name"] = cfg.azure_account_name
    if cfg.anonymous:
        opts["token" if cfg.protocol == "gcs" else "anon"] = "anon" if cfg.protocol == "gcs" else True
    note = {"s3": "# Credentials: the standard AWS chain (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, ~/.aws, or an instance role).",
            "gcs": "# Credentials: GOOGLE_APPLICATION_CREDENTIALS or Application Default Credentials.",
            "azure": "# Credentials: set AZURE_STORAGE_KEY (or use Azure default credentials).", "local": ""}[cfg.protocol]
    reader = {"parquet": "read_parquet", "csv": "read_csv", "tsv": "read_csv", "json": "read_json", "jsonl": "read_json", "excel": "read_excel"}[kind]
    extra = ", sep='\\t'" if kind == "tsv" else ", lines=True" if kind == "jsonl" else ""
    imp = ""
    if cfg.protocol == "azure":
        so, imp = f", storage_options={{**{opts!r}, 'account_key': os.environ.get('AZURE_STORAGE_KEY')}}", "import os"
    else:
        so = f", storage_options={opts!r}" if opts else ""
    head = f".head({int(v['limit'])})" if v["limit"] else ""
    if any(c in str(v["path"]) for c in "*?["):  # a glob: read every matching file and stack them
        open_opts = so.replace(", storage_options=", ", **") if so else ""
        return lines("import fsspec", "import pandas as pd", imp, note,
                     f"_files = fsspec.open_files({target!r}, mode='rb'{open_opts})",
                     f"{out} = pd.concat([pd.{reader}(_f.open(){extra}) for _f in _files], ignore_index=True){head}")
    return lines("import pandas as pd", imp, note, f"{out} = pd.{reader}({target!r}{extra}{so}){head}")


def mlflow_register(v: V) -> str:
    alias = (f"mlflow.MlflowClient().set_registered_model_alias({v['model_name']!r}, {v['alias']!r}, _mv_{v['var']}.version)" if v["alias"] else "")
    return lines("import mlflow",
                 "# Registers into the server in MLFLOW_TRACKING_URI (Athena's local store is sqlite:///<home>/.athena/mlflow/mlflow.db).",
                 f"with mlflow.start_run(run_name='register {v['model_name']}'):",
                 f"    _info_{v['var']} = mlflow.sklearn.log_model({v['in_model']}, name='model', serialization_format='cloudpickle')",
                 f"_mv_{v['var']} = mlflow.register_model(_info_{v['var']}.model_uri, {v['model_name']!r})", alias,
                 f"{v['out_report']} = f'Registered {v['model_name']} version {{_mv_{v['var']}.version}}'", f"print({v['out_report']})")


def mlflow_load(v: V) -> str:
    uri = f"models:/{v['model_name']}@{v['alias']}" if str(v["alias"]).strip() else f"models:/{v['model_name']}/{v['version'] or 'latest'}"
    return lines("import mlflow", "# Reads from the server in MLFLOW_TRACKING_URI.", f"{v['out_model']} = mlflow.sklearn.load_model({uri!r})")


EXPORT: dict[str, Template] = {f.__name__: f for f in [db_connector, duckdb_sql, storage_loader, mlflow_register, mlflow_load]}
