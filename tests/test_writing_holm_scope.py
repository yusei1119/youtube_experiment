from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from scripts.analysis import analyze_writing_task as writing


class WritingHolmScopeTests(unittest.TestCase):
    def test_paired_holm_is_applied_separately_to_each_metric(self) -> None:
        participants = [f"A{index:03d}" for index in range(1, 7)]
        rows = []
        for participant_index, participant_id in enumerate(participants):
            for condition_index, condition in enumerate(writing.CONDITIONS_90):
                row = {
                    "participant_id": participant_id,
                    "video_condition": condition,
                }
                for metric_index, metric in enumerate(writing.ALL_METRICS):
                    row[metric] = (
                        100 * metric_index
                        + 10 * participant_index
                        + condition_index
                    )
                rows.append(row)
        data = pd.DataFrame(rows)

        _, pairwise, _ = writing.paired_analysis(data, writing.CONDITIONS_90)

        for metric, metric_rows in pairwise.groupby("metric"):
            expected = writing.holm_adjust(metric_rows["p_raw"].astype(float).tolist())
            np.testing.assert_allclose(
                metric_rows["p_holm_within_metric"].to_numpy(float),
                expected,
            )
            self.assertEqual(set(metric_rows["holm_family"]), {metric})
            self.assertEqual(set(metric_rows["holm_family_size"]), {3})

    def test_omnibus_results_are_not_adjusted_across_metrics(self) -> None:
        participants = [f"A{index:03d}" for index in range(1, 7)]
        rows = []
        for participant_index, participant_id in enumerate(participants):
            for condition_index, condition in enumerate(writing.CONDITIONS_90):
                row = {
                    "participant_id": participant_id,
                    "video_condition": condition,
                }
                for metric_index, metric in enumerate(writing.ALL_METRICS):
                    row[metric] = (
                        metric_index + participant_index + condition_index
                    )
                rows.append(row)

        omnibus, _, _ = writing.paired_analysis(
            pd.DataFrame(rows),
            writing.CONDITIONS_90,
        )

        self.assertNotIn("p_holm_across_metrics", omnibus.columns)
        self.assertIn("significance_unadjusted", omnibus.columns)


if __name__ == "__main__":
    unittest.main()
