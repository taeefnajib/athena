from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path.home() / ".athena"
    node_timeout_s: int = 300
    cache_max_gb: float = 2.0
    log_level: str = "INFO"
    allow_custom_code: bool = True

    model_config = {"env_prefix": "ATHENA_"}

    @property
    def pipelines_dir(self) -> Path:
        return self.data_dir / "pipelines"


settings = Settings()
