import pandas as pd
import numpy as np
from athena.schemas.artifacts import DataframePreview


def preview_dataframe(df: pd.DataFrame) -> DataframePreview:
    preview_df = df.head(50).iloc[:, :50]
    # Convert to JSON-safe types
    rows = []
    for row in preview_df.itertuples(index=False):
        clean = []
        for v in row:
            if isinstance(v, (np.integer,)):
                clean.append(int(v))
            elif isinstance(v, (np.floating,)):
                clean.append(None if np.isnan(v) else float(v))
            elif isinstance(v, float) and np.isnan(v):
                clean.append(None)
            else:
                clean.append(v)
        rows.append(clean)
    return DataframePreview(
        columns=list(preview_df.columns.astype(str)),
        rows=rows,
        shape=(len(df), len(df.columns)),
    )


def get_target_column(df: pd.DataFrame) -> str:
    if "target" in df.columns:
        return "target"
    return df.columns[-1]
