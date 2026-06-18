from pydantic import BaseModel, Field
from typing import Literal, Any, Union, Annotated


class DataframePreview(BaseModel):
    kind: Literal["dataframe"] = "dataframe"
    columns: list[str]
    rows: list[list[Any]]
    shape: tuple[int, int]


class MetricsPreview(BaseModel):
    kind: Literal["metrics"] = "metrics"
    values: dict[str, float]


class PlotPreview(BaseModel):
    kind: Literal["plot"] = "plot"
    format: Literal["png_base64"] = "png_base64"
    data: str


class ModelPreview(BaseModel):
    kind: Literal["model"] = "model"
    summary: str


class TextPreview(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    download_filename: str | None = None
    download_content: str | None = None  # base64-encoded file content


class ColumnInfo(BaseModel):
    name: str
    dtype: str
    missing: int
    missing_pct: float
    unique: int
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    top_values: list[str] | None = None


class DataframeInfoPreview(BaseModel):
    kind: Literal["dataframe_info"] = "dataframe_info"
    shape: tuple[int, int]
    duplicates: int
    total_missing: int
    missing_pct: float
    info_columns: list[ColumnInfo]


ArtifactPreview = Annotated[
    Union[DataframePreview, MetricsPreview, PlotPreview, ModelPreview, TextPreview, DataframeInfoPreview],
    Field(discriminator="kind"),
]
