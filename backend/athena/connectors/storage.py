"""Object storage through fsspec: Amazon S3 and S3-compatible stores (MinIO, Cloudflare R2, …),
Google Cloud Storage, Azure Blob / Data Lake, and local folders."""
from __future__ import annotations

import importlib.util
import posixpath
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, SecretStr

from athena.sdk.connector import ConnectorBase, Resource, TestResult, connector
from athena.sdk.node import ui

if TYPE_CHECKING:
    import pandas as pd

# protocol -> (fsspec protocol, driver module, pip extra)
DRIVERS = {"s3": ("s3", "s3fs", "s3"), "gcs": ("gcs", "gcsfs", "gcs"), "azure": ("abfs", "adlfs", "azure"), "local": ("file", None, None)}
FORMATS = ("auto", "csv", "tsv", "parquet", "json", "jsonl", "excel")


class StorageConfig(BaseModel):
    protocol: Literal["s3", "gcs", "azure", "local"] = "s3"
    bucket: str = ""
    """Bucket (S3/GCS), container (Azure) or base folder (local)."""
    prefix: str = ""
    endpoint_url: str = ""
    region: str = ""
    access_key_id: str = ""
    secret_access_key: SecretStr = SecretStr("")
    azure_account_name: str = ""
    azure_account_key: SecretStr = SecretStr("")
    gcs_credentials_file: str = ""
    anonymous: bool = False


def filesystem(cfg: StorageConfig) -> Any:
    import fsspec

    proto, module, extra = DRIVERS[cfg.protocol]
    if module and importlib.util.find_spec(module) is None:
        raise RuntimeError(f"The {cfg.protocol} driver isn't installed. Run: pip install 'athena-backend[{extra}]'")
    opts: dict[str, Any] = {}
    if cfg.protocol == "s3":
        opts["anon"] = cfg.anonymous
        if cfg.access_key_id:
            opts.update(key=cfg.access_key_id, secret=cfg.secret_access_key.get_secret_value())
        client: dict[str, str] = {}
        if cfg.endpoint_url:
            client["endpoint_url"] = cfg.endpoint_url
        if cfg.region:
            client["region_name"] = cfg.region
        if client:
            opts["client_kwargs"] = client
    elif cfg.protocol == "gcs":
        opts["token"] = "anon" if cfg.anonymous else (cfg.gcs_credentials_file or None)
    elif cfg.protocol == "azure":
        opts.update(account_name=cfg.azure_account_name or None, anon=cfg.anonymous)
        if cfg.azure_account_key.get_secret_value():
            opts["account_key"] = cfg.azure_account_key.get_secret_value()
    return fsspec.filesystem(proto, **opts)


def root(cfg: StorageConfig) -> str:
    base = cfg.bucket.strip().rstrip("/\\") if cfg.protocol == "local" else cfg.bucket.strip().strip("/")
    if not base:
        raise ValueError("Enter a bucket, container or folder")
    prefix = cfg.prefix.strip().strip("/")
    return f"{base}/{prefix}" if prefix else base


def full_path(cfg: StorageConfig, path: str) -> str:
    """A path relative to the connection's bucket/prefix (an absolute bucket path is also accepted)."""
    path = path.strip()
    base = root(cfg)
    if not path:
        return base
    if path.startswith(base):
        return path
    return f"{base}/{path.lstrip('/')}"


def url(cfg: StorageConfig, path: str) -> str:
    scheme = {"s3": "s3", "gcs": "gs", "azure": "abfs", "local": "file"}[cfg.protocol]
    return f"{scheme}://{full_path(cfg, path)}"


def detect_format(path: str, fmt: str = "auto") -> str:
    if fmt != "auto":
        return fmt
    ext = posixpath.splitext(path.lower().rstrip("/"))[1]
    return {".parquet": "parquet", ".pq": "parquet", ".csv": "csv", ".txt": "csv", ".tsv": "tsv", ".json": "json",
            ".jsonl": "jsonl", ".ndjson": "jsonl", ".xlsx": "excel", ".xls": "excel"}.get(ext, "parquet" if ext == "" else "")


def read_frame(fs: Any, path: str, fmt: str = "auto", limit: int | None = None) -> pd.DataFrame:
    import pandas as pd

    kind = detect_format(path, fmt)
    if not kind:
        raise ValueError(f"Can't tell the format of {path!r}. Choose one under Format.")
    if kind == "parquet":
        df = pd.read_parquet(path, filesystem=fs)   # works for single files and partitioned folders
    else:
        with fs.open(path, "rb") as f:
            if kind in ("csv", "tsv"):
                df = pd.read_csv(f, sep="\t" if kind == "tsv" else ",", nrows=limit or None)
            elif kind == "json":
                df = pd.read_json(f)
            elif kind == "jsonl":
                df = pd.read_json(f, lines=True, nrows=limit or None)
            else:
                df = pd.read_excel(f)
    return df.head(limit) if limit else df


@connector(
    "storage", label="Object Storage", category="storage",
    description="Read files from Amazon S3 (and S3-compatible stores such as MinIO or R2), Google Cloud Storage, "
                "Azure Blob / Data Lake, or a local folder.",
    library="fsspec (s3fs, gcsfs, adlfs)", license="BSD-3-Clause (fsspec, s3fs, gcsfs, adlfs)",
    fields={
        "protocol": ui("Storage"),
        "bucket": ui("Bucket / container / folder"),
        "prefix": ui("Prefix", help="Optional sub-folder that paths are relative to"),
        "endpoint_url": ui("Endpoint URL", help="S3-compatible stores only, e.g. http://localhost:9000 for MinIO"),
        "region": ui("Region", help="S3 only, e.g. eu-west-1"),
        "access_key_id": ui("Access key ID", help="S3. Empty = the standard AWS credential chain (env vars, ~/.aws, instance role)"),
        "secret_access_key": ui("Secret access key", help="S3. Stored in your OS keychain, or env://VAR"),
        "azure_account_name": ui("Azure account name"),
        "azure_account_key": ui("Azure account key", help="Stored in your OS keychain, or env://VAR. Empty = Azure default credentials"),
        "gcs_credentials_file": ui("GCS credentials file", help="Path to a service-account JSON. Empty = Application Default Credentials"),
        "anonymous": ui("Public bucket (no credentials)"),
    },
    extras={"Amazon S3 / MinIO / R2": "pip install 'athena-backend[s3]'",
            "Google Cloud Storage": "pip install 'athena-backend[gcs]'",
            "Azure Blob / ADLS": "pip install 'athena-backend[azure]'"},
)
class StorageConnector(ConnectorBase):
    Config = StorageConfig

    def test(self, cfg: StorageConfig) -> TestResult:
        try:
            items = filesystem(cfg).ls(root(cfg), detail=False)
        except Exception as exc:
            return TestResult(False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}")
        return TestResult(True, f"Connected · {len(items)} items in {root(cfg)}", {"items": len(items)})

    def list(self, cfg: StorageConfig, path: str | None = None) -> list[Resource]:
        fs, base = filesystem(cfg), root(cfg)
        target = full_path(cfg, path or "")
        out = []
        for entry in fs.ls(target, detail=True):
            name = posixpath.basename(str(entry["name"]).rstrip("/").replace("\\", "/"))
            rel = posixpath.relpath(str(entry["name"]).replace("\\", "/"), base.replace("\\", "/"))
            is_dir = entry.get("type") == "directory"
            out.append(Resource(rel, name, "folder" if is_dir else "file", is_dir))
        return sorted(out, key=lambda r: (not r.has_children, r.name))

    def read(self, cfg: StorageConfig, query: str, limit: int | None = None) -> pd.DataFrame:
        """``query`` is a path relative to the bucket/prefix."""
        return read_frame(filesystem(cfg), full_path(cfg, query), "auto", limit)
