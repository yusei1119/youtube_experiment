import unittest
from pathlib import Path

import pandas as pd

from scripts.analysis.analyze_youtube_logs import (
    apply_participant_corrections,
    apply_session_corrections,
    build_summary_table,
    load_participant_corrections,
    load_session_corrections,
)


class ParticipantCorrectionTests(unittest.TestCase):
    def test_selected_viewing_duration_is_written_to_summary_csv_row(self):
        video = pd.DataFrame(
            [
                {
                    "participant_id": "B001",
                    "session_id": "session-1",
                    "video_index": 0,
                    "video_title": "sample",
                    "video_category": "Music",
                    "watched_sec": 12.0,
                    "duration_sec": 20.0,
                    "first_time": pd.Timestamp("2026-07-31T00:00:00Z"),
                    "last_time": pd.Timestamp("2026-07-31T00:00:12Z"),
                    "completed": False,
                    "early_skip": False,
                    "viewing_duration_minutes": 15,
                    "session_started_at": pd.Timestamp("2026-07-31T00:00:00Z"),
                    "session_finished_at": pd.Timestamp("2026-07-31T00:05:00Z"),
                }
            ]
        )

        summary = build_summary_table(video)

        self.assertEqual(summary.loc[0, "viewing_duration_minutes"], 15)
        self.assertEqual(summary.loc[0, "session_minutes"], 5)
        self.assertAlmostEqual(summary.loc[0, "logged_session_minutes"], 0.2)

    def test_project_correction_file_contains_requested_rules(self):
        correction_path = (
            Path(__file__).resolve().parents[1]
            / "data/corrections/youtube_participant_corrections.csv"
        )

        corrections = load_participant_corrections(correction_path)

        self.assertEqual(
            corrections["source_participant_id"].tolist(),
            [
                "A014",
                "A029",
                "AO32",
                "A032",
                "A040",
                "A042",
                "A042-V2",
                "A043",
                "A052",
                "A057",
                "A067",
                "A067-V2",
                "A069",
                "A069-V2",
            ],
        )

    def test_normalizes_ids_and_adopts_only_usable_redo_logs(self):
        logs = pd.DataFrame(
            [
                {"participant_id": "Ａ042", "session_id": "old-42"},
                {"participant_id": "Ａ042-V2", "session_id": "new-42"},
                {"participant_id": "AO32", "session_id": "a031"},
                {"participant_id": "A067", "session_id": "old-67"},
                {"participant_id": "A067-v2", "session_id": "new-67"},
                {"participant_id": "A069", "session_id": "old-69"},
                {"participant_id": "A069-V2", "session_id": "failed-new-69"},
                {"participant_id": "A070", "session_id": "unchanged"},
            ]
        )
        corrections = pd.DataFrame(
            [
                ["A042", "", "exclude", "old"],
                ["A042-V2", "A042", "rename", "adopt"],
                ["AO32", "A031", "rename", "typo"],
                ["A067", "", "exclude", "old"],
                ["A067-V2", "A067", "rename", "adopt"],
                ["A069", "", "exclude", "old"],
                ["A069-V2", "", "exclude", "failed redo"],
            ],
            columns=[
                "source_participant_id",
                "corrected_participant_id",
                "action",
                "reason",
            ],
        )

        corrected, report = apply_participant_corrections(logs, corrections)

        self.assertEqual(
            corrected["participant_id"].tolist(),
            ["A042", "A031", "A067", "A070"],
        )
        self.assertEqual(
            corrected["session_id"].tolist(),
            ["new-42", "a031", "new-67", "unchanged"],
        )
        self.assertTrue((report["status"] == "applied").all())
        self.assertTrue((report["matched_event_count"] == 1).all())

    def test_rejects_unconfigured_target_collision(self):
        logs = pd.DataFrame(
            [
                {"participant_id": "A031", "session_id": "existing"},
                {"participant_id": "AO32", "session_id": "typo"},
            ]
        )
        corrections = pd.DataFrame(
            [["AO32", "A031", "rename", "typo"]],
            columns=[
                "source_participant_id",
                "corrected_participant_id",
                "action",
                "reason",
            ],
        )

        with self.assertRaisesRegex(ValueError, "意図せず統合"):
            apply_participant_corrections(logs, corrections)

    def test_allows_target_when_correction_source_is_absent(self):
        logs = pd.DataFrame(
            [{"participant_id": "A031", "session_id": "correct"}]
        )
        corrections = pd.DataFrame(
            [["AO32", "A031", "rename", "typo"]],
            columns=[
                "source_participant_id",
                "corrected_participant_id",
                "action",
                "reason",
            ],
        )

        corrected, report = apply_participant_corrections(logs, corrections)

        self.assertEqual(corrected["participant_id"].tolist(), ["A031"])
        self.assertEqual(report.loc[0, "status"], "not_found")

    def test_excludes_failed_sessions_and_trims_delayed_tail(self):
        logs = pd.DataFrame(
            [
                {
                    "participant_id": "A009",
                    "session_id": "failed",
                    "server_time": "2026-07-29T00:00:00+00:00",
                },
                {
                    "participant_id": "A051",
                    "session_id": "trimmed",
                    "server_time": "2026-07-29T00:00:00+00:00",
                },
                {
                    "participant_id": "A051",
                    "session_id": "trimmed",
                    "server_time": "2026-07-29T00:10:00+00:00",
                },
                {
                    "participant_id": "A051",
                    "session_id": "trimmed",
                    "server_time": "2026-07-29T03:00:00+00:00",
                },
            ]
        )
        corrections = pd.DataFrame(
            [
                ["failed", "exclude", "", "failed start"],
                [
                    "trimmed",
                    "trim_after",
                    "2026-07-29T00:10:00+00:00",
                    "delayed tail",
                ],
            ],
            columns=["session_id", "action", "cutoff_server_time", "reason"],
        )

        corrected, report = apply_session_corrections(logs, corrections)

        self.assertEqual(corrected["session_id"].tolist(), ["trimmed", "trimmed"])
        self.assertEqual(report["removed_event_count"].tolist(), [1, 1])
        self.assertEqual(report["retained_event_count"].tolist(), [0, 2])

    def test_project_session_file_contains_six_rules(self):
        correction_path = (
            Path(__file__).resolve().parents[1]
            / "data/corrections/youtube_session_corrections.csv"
        )

        corrections = load_session_corrections(correction_path)

        self.assertEqual(len(corrections), 6)
        self.assertEqual(
            corrections["action"].value_counts().to_dict(),
            {"exclude": 4, "trim_after": 2},
        )


if __name__ == "__main__":
    unittest.main()
