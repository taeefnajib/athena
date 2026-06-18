import json
import shutil
from pathlib import Path
from athena.config import settings
from athena.schemas.pipeline import PipelineSpec


def _autosave_dir() -> Path:
    d = settings.data_dir / "autosave"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_autosave(spec: PipelineSpec) -> None:
    d = _autosave_dir()
    latest = d / "latest.athena"
    # Rotate
    for i in range(4, 0, -1):
        src = d / f"autosave-{i}.athena"
        dst = d / f"autosave-{i+1}.athena"
        if src.exists():
            shutil.copy2(src, dst)
    if latest.exists():
        shutil.copy2(latest, d / "autosave-1.athena")
    tmp = d / "latest.athena.tmp"
    tmp.write_text(json.dumps(spec.model_dump(), indent=2), encoding="utf-8")
    tmp.replace(latest)


def load_latest_autosave() -> PipelineSpec | None:
    path = _autosave_dir() / "latest.athena"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return PipelineSpec(**data)
