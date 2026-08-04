from __future__ import annotations

import unittest

import pandas as pd

from scripts.analysis import analyze_writing_task as writing
from scripts.analysis.writing_text_metrics import calculate_text_metrics
from scripts.export.export_writing_60_responses import flatten_long, flatten_wide


class Writing60MetricExportTests(unittest.TestCase):
    def _submission(self) -> dict[str, object]:
        responses = []
        for index, category in enumerate(writing.CATEGORIES, start=1):
            responses.append({
                "id": index,
                "category_key": category,
                "question_id": f"{category}_v1",
                "display_order": index,
                "category_label": category,
                "variant_number": 1,
                "question_text": f"Q{index}",
                "answer_text": "あ" * (60 + index),
                "answer_char_count": 60 + index,
                "min_char_count": 60,
                "max_char_count": 200,
                "min_chars_reached_text": "あ" * 60,
                "chars_after_min": index,
                "deleted_char_count": index * 2,
                "min_chars_reached_sec": index * 3.0,
                "first_shown_sec": index * 0.5,
                "latency_sec": index * 0.4,
                "writing_duration_sec": index * 4.0,
                "active_writing_sec": index * 2.0,
                "idle_after_writing_started_sec": index * 0.5,
                "visits": 1,
                "revision_count": 0,
            })
        return {
            "id": "submission-1",
            "participant_id": "B001",
            "viewing_duration": "5min",
            "writing_60_responses": responses,
        }

    def test_wide_export_contains_question_values_and_five_question_means(self) -> None:
        row = flatten_wide([self._submission()])[0]

        self.assertEqual(row["general_min_chars_reached_text"], "あ" * 60)
        self.assertEqual(row["mean_chars_after_min"], 3.0)
        self.assertEqual(row["mean_deleted_char_count"], 6.0)
        self.assertEqual(row["mean_min_chars_reached_sec"], 9.0)
        self.assertEqual(row["mean_latency_sec"], 1.2)
        self.assertNotIn("general_active_writing_sec", row)
        self.assertNotIn("mean_active_writing_sec", row)
        self.assertNotIn("mean_idle_after_writing_started_sec", row)

    def test_long_export_repeats_submission_means_for_each_question(self) -> None:
        rows = flatten_long([self._submission()])

        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["mean_chars_after_min"] == 3.0 for row in rows))
        self.assertEqual(rows[0]["min_chars_reached_text"], "あ" * 60)
        self.assertNotIn("active_writing_sec", rows[0])
        self.assertNotIn("idle_after_writing_started_sec", rows[0])


class Writing60MetricAnalysisTests(unittest.TestCase):
    def test_extract_metrics_outputs_question_values_and_overall_means(self) -> None:
        row: dict[str, object] = {
            "participant_id": "B001",
            "source_row": 2,
            "viewing_duration": "5min",
            "total_duration_sec": 100.0,
            "total_answer_duration_sec": 90.0,
            "total_char_count": 350,
        }
        for index, category in enumerate(writing.CATEGORIES, start=1):
            row.update({
                f"{category}_question_id": f"{category}_v1",
                f"{category}_variant_number": 1,
                f"{category}_display_order": index,
                f"{category}_question_text": f"Q{index}",
                f"{category}_answer_text": "回答",
                f"{category}_answer_char_count": 70,
                f"{category}_min_char_count": 60,
                f"{category}_max_char_count": 200,
                f"{category}_min_chars_reached_text": "下限到達文章",
                f"{category}_chars_after_min": index,
                f"{category}_deleted_char_count": index * 2,
                f"{category}_min_chars_reached_sec": index * 3.0,
                f"{category}_latency_sec": index * 0.4,
                f"{category}_writing_duration_sec": index * 4.0,
                f"{category}_active_writing_sec": index * 2.0,
                f"{category}_idle_after_writing_started_sec": index * 0.5,
            })

        result, question_data = writing.extract_writing_metrics(pd.DataFrame([row]))

        self.assertEqual(result.loc[0, "Mean_chars_after_min"], 3.0)
        self.assertEqual(result.loc[0, "Mean_deleted_char_count"], 6.0)
        self.assertEqual(result.loc[0, "Mean_min_chars_reached_sec"], 9.0)
        self.assertEqual(result.loc[0, "Mean_latency_sec"], 1.2)
        self.assertNotIn("Mean_active_writing_sec", result)
        self.assertNotIn("Mean_idle_after_writing_started_sec", result)
        self.assertEqual(len(question_data), 5)
        self.assertEqual(question_data.iloc[0]["min_chars_reached_text"], "下限到達文章")
        self.assertEqual(question_data.iloc[4]["chars_after_min"], 5)
        self.assertNotIn("active_writing_sec", question_data)
        self.assertNotIn("idle_after_writing_started_sec", question_data)

    def test_japanese_text_content_metrics_are_interpretable(self) -> None:
        metrics = calculate_text_metrics(
            "私は場面の変化を強く感じた。そのため、自分の価値観を考え直した。"
        )

        self.assertGreater(metrics["content_word_count"], 0)
        self.assertGreater(metrics["lexical_diversity_mattr"], 0)
        self.assertLessEqual(metrics["lexical_diversity_mattr"], 1)
        self.assertGreater(metrics["causal_marker_rate"], 0)
        self.assertGreater(metrics["reflection_marker_rate"], 0)
        self.assertGreater(metrics["sentence_length_tokens"], 0)

    def test_text_metrics_are_added_as_five_question_means(self) -> None:
        rows = []
        for index, category in enumerate(writing.CATEGORIES):
            rows.append({
                "participant_id": "B001",
                "source_row": 2,
                "viewing_duration": "5min",
                "category": category,
                "question_id": f"{category}_v1",
                "answer_text": "私は映像について考えた。そのため印象が変わった。",
            })
        data = pd.DataFrame([{
            "participant_id": "B001",
            "source_row": 2,
            "viewing_duration": "5min",
        }])

        result, questions = writing.add_text_content_metrics(
            data, pd.DataFrame(rows)
        )

        self.assertEqual(len(questions), 5)
        self.assertTrue(result.loc[0, "Mean_content_word_count"] > 0)
        self.assertAlmostEqual(
            result.loc[0, "Mean_reflection_marker_rate"],
            questions["reflection_marker_rate"].mean(),
        )

    def test_text_trend_adjusts_the_seven_metric_family(self) -> None:
        data_rows = []
        question_rows = []
        for participant_index in range(12):
            source_row = participant_index + 2
            duration = f"{5 * (participant_index // 2 + 1)}min"
            data_rows.append({
                "participant_id": f"B{participant_index + 1:03d}",
                "source_row": source_row,
                "viewing_duration": duration,
            })
            for category_index, category in enumerate(writing.CATEGORIES):
                row = {
                    "source_row": source_row,
                    "category": category,
                    "question_id": f"{category}_v{category_index % 3 + 1}",
                }
                for measure_index, measure in enumerate(
                    writing.TEXT_QUESTION_MEASURES
                ):
                    row[measure] = participant_index + measure_index / 10
                question_rows.append(row)

        result = writing.text_content_trend_analysis(
            pd.DataFrame(data_rows), pd.DataFrame(question_rows), seed=7,
            permutations=99,
        )

        self.assertEqual(len(result), 7)
        self.assertEqual(set(result["n"]), {12})
        self.assertTrue((result["rho"] > 0.98).all())
        self.assertTrue((result["p_holm_across_text_metrics"] <= 1).all())


if __name__ == "__main__":
    unittest.main()
