import json
from pathlib import Path
from athena.schemas.pipeline import PipelineSpec


def save_pipeline(path: str, spec: PipelineSpec) -> None:
    p = Path(path)
    if not p.parent.exists():
        raise ValueError(f"Directory does not exist: {p.parent}")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(spec.model_dump(), indent=2), encoding="utf-8")
    tmp.replace(p)


def load_pipeline(path: str) -> PipelineSpec:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Pipeline file not found: {path}")
    data = json.loads(p.read_text(encoding="utf-8"))
    return PipelineSpec(**data)
