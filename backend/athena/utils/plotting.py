import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from athena.schemas.artifacts import PlotPreview

# Categorical series colours, in this fixed order (validated: CVD-separable on white; pair with direct labels).
SERIES = ("#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647")


def style_axes(ax) -> None:  # type: ignore[no-untyped-def]
    """Recessive chart chrome: no top/right spines, hairline light-grey axes and grid, grey tick labels."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#cccccc"); ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors="#666666", labelsize=8.5, length=0)
    ax.grid(True, color="#eeeeee", linewidth=0.8); ax.set_axisbelow(True)
    ax.xaxis.label.set_color("#444444"); ax.yaxis.label.set_color("#444444")


def fig_to_base64(fig: plt.Figure) -> str:  # type: ignore[name-defined]
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=80)
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return data


def fig_to_plot_preview(fig: plt.Figure) -> PlotPreview:  # type: ignore[name-defined]
    return PlotPreview(data=fig_to_base64(fig))
