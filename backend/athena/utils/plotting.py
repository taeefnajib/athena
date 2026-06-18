import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from athena.schemas.artifacts import PlotPreview


def fig_to_base64(fig: plt.Figure) -> str:  # type: ignore[name-defined]
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=80)
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return data


def fig_to_plot_preview(fig: plt.Figure) -> PlotPreview:  # type: ignore[name-defined]
    return PlotPreview(data=fig_to_base64(fig))
