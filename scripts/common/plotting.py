"""分析図で共通利用する描画スタイルと有意差注釈。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd


_TIMES_NEW_ROMAN_PATHS = (
    Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
    Path("/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf"),
    Path("/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf"),
)
_FONT_REGISTERED = False


def _register_times_new_roman() -> None:
    """Matplotlibのキャッシュ状態にかかわらずTimes New Romanを登録する。"""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    for path in _TIMES_NEW_ROMAN_PATHS:
        if path.exists():
            font_manager.fontManager.addfont(path)
    _FONT_REGISTERED = True


def configure_analysis_plot_style() -> None:
    """論文・発表用の大きなTimes New Romanと太い目盛りを設定する。"""
    _register_times_new_roman()
    plt.rcParams.update(
        {
            "font.family": "Times New Roman",
            "font.size": 14,
            "mathtext.fontset": "stix",
            "axes.linewidth": 1.8,
            "axes.titlesize": 16,
            "axes.titleweight": "bold",
            "axes.labelsize": 14,
            "axes.labelweight": "bold",
            "xtick.labelsize": 13,
            "ytick.labelsize": 13,
            "xtick.direction": "in",
            "ytick.direction": "in",
            "xtick.major.size": 6,
            "ytick.major.size": 6,
            "xtick.major.width": 1.8,
            "ytick.major.width": 1.8,
            "xtick.minor.size": 3.5,
            "ytick.minor.size": 3.5,
            "xtick.minor.width": 1.4,
            "ytick.minor.width": 1.4,
            "legend.fontsize": 12,
        }
    )


def add_significance_bars(
    ax: plt.Axes,
    pairwise: pd.DataFrame,
    metric: str,
    group_order: Sequence[str],
    *,
    p_column: str = "p_holm_within_metric",
) -> int:
    """Holm補正後に有意なペアを、軸上部へブラケットと星印で描く。"""
    required = {"metric", "condition_1", "condition_2", p_column}
    if pairwise.empty or not required.issubset(pairwise.columns):
        return 0

    positions = {str(group): index for index, group in enumerate(group_order)}
    rows: list[tuple[int, int, float]] = []
    metric_rows = pairwise[pairwise["metric"] == metric]
    for result in metric_rows.itertuples(index=False):
        condition_1 = str(getattr(result, "condition_1"))
        condition_2 = str(getattr(result, "condition_2"))
        p_value = float(getattr(result, p_column))
        if (
            condition_1 not in positions
            or condition_2 not in positions
            or not np.isfinite(p_value)
            or p_value >= 0.05
        ):
            continue
        left, right = sorted((positions[condition_1], positions[condition_2]))
        rows.append((left, right, p_value))

    rows.sort(key=lambda row: (row[1] - row[0], row[0]))
    if not rows:
        return 0

    transform = ax.get_xaxis_transform()
    level_step = min(0.045, 0.11 / max(len(rows) - 1, 1))
    for level, (left, right, p_value) in enumerate(rows):
        y = 0.78 + level * level_step
        bracket_height = 0.012
        ax.plot(
            [left, left, right, right],
            [y, y + bracket_height, y + bracket_height, y],
            transform=transform,
            color="black",
            linewidth=1.8,
            clip_on=False,
            zorder=10,
        )
        stars = "***" if p_value < 0.001 else "**" if p_value < 0.01 else "*"
        ax.text(
            (left + right) / 2,
            y + bracket_height + 0.004,
            stars,
            transform=transform,
            ha="center",
            va="bottom",
            fontsize=16,
            fontweight="bold",
            clip_on=False,
            zorder=11,
        )
    return len(rows)
