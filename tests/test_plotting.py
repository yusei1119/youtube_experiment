from __future__ import annotations

import unittest

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from scripts.common.plotting import (
    add_significance_bars,
    configure_analysis_plot_style,
)


class AnalysisPlottingTests(unittest.TestCase):
    def tearDown(self) -> None:
        plt.close("all")

    def test_times_new_roman_and_thick_ticks_are_configured(self) -> None:
        configure_analysis_plot_style()
        fig, ax = plt.subplots()
        ax.set_xticks([0], ["Condition"])
        fig.canvas.draw()

        self.assertEqual(
            ax.get_xticklabels()[0].get_fontproperties().get_name(),
            "Times New Roman",
        )
        self.assertGreaterEqual(
            ax.xaxis.majorTicks[0].tick1line.get_markeredgewidth(),
            1.8,
        )

    def test_only_holm_significant_pairs_receive_stars(self) -> None:
        pairwise = pd.DataFrame(
            [
                {
                    "metric": "score",
                    "condition_1": "a",
                    "condition_2": "b",
                    "p_holm_within_metric": 0.049,
                },
                {
                    "metric": "score",
                    "condition_1": "a",
                    "condition_2": "c",
                    "p_holm_within_metric": 0.009,
                },
                {
                    "metric": "score",
                    "condition_1": "b",
                    "condition_2": "c",
                    "p_holm_within_metric": 0.2,
                },
            ]
        )
        _, ax = plt.subplots()

        count = add_significance_bars(ax, pairwise, "score", ("a", "b", "c"))

        self.assertEqual(count, 2)
        self.assertEqual([text.get_text() for text in ax.texts], ["*", "**"])


if __name__ == "__main__":
    unittest.main()
