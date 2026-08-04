from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts.common.participant_selection import (
    canonicalize_participant_id,
    filter_excluded_participants,
    filter_selected_participants,
    load_participant_exclusions,
    load_participant_selection,
    parse_included,
)


ROOT = Path(__file__).resolve().parents[1]


class ParticipantSelectionTests(unittest.TestCase):
    def test_repository_selection_has_48_included_participants(self) -> None:
        selection, included = load_participant_selection(
            ROOT / "data/corrections/analysis_participants.csv"
        )
        self.assertEqual(len(selection), 57)
        self.assertEqual(len(included), 48)
        self.assertIn("A031", included)
        self.assertIn("A042", included)
        self.assertIn("A067", included)
        self.assertNotIn("A069", included)

    def test_id_notation_is_canonicalized(self) -> None:
        self.assertEqual(canonicalize_participant_id(" ａ42 "), "A042")
        self.assertEqual(canonicalize_participant_id("A0042"), "A042")
        self.assertEqual(canonicalize_participant_id("ｂ0077"), "B077")

    def test_repository_60_exclusions(self) -> None:
        exclusions, excluded = load_participant_exclusions(
            ROOT / "data/corrections/analysis_excluded_participants_60.csv"
        )
        self.assertEqual(len(exclusions), 3)
        self.assertEqual(excluded, {"B077", "B085", "B089"})

    def test_japanese_boolean_values_are_supported(self) -> None:
        self.assertTrue(parse_included("採用"))
        self.assertFalse(parse_included("除外"))

    def test_duplicate_ids_after_normalization_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selection.csv"
            path.write_text(
                "participant_id,included,note\nA042,true,x\nＡ０４２,false,y\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "重複"):
                load_participant_selection(path)

    def test_filter_marks_excluded_rows(self) -> None:
        data = pd.DataFrame(
            {"source_row": [2, 3], "participant_id": ["A001", "A069"]}
        )
        report = data.copy()
        report["included"] = True
        report["reason"] = "candidate"
        filtered = filter_selected_participants(data, report, {"A001"})
        self.assertEqual(filtered["participant_id"].tolist(), ["A001"])
        excluded = report.loc[report["participant_id"] == "A069"].iloc[0]
        self.assertFalse(bool(excluded["included"]))
        self.assertEqual(
            excluded["reason"], "excluded_by_participant_selection"
        )

    def test_filter_60_exclusions_marks_report(self) -> None:
        data = pd.DataFrame(
            {"source_row": [2, 3], "participant_id": ["B076", "B077"]}
        )
        report = data.copy()
        report["included"] = True
        report["reason"] = "candidate"
        filtered = filter_excluded_participants(data, report, {"B077"})
        self.assertEqual(filtered["participant_id"].tolist(), ["B076"])
        excluded = report.loc[report["participant_id"] == "B077"].iloc[0]
        self.assertFalse(bool(excluded["included"]))
        self.assertEqual(
            excluded["reason"], "excluded_by_participant_exclusions"
        )


if __name__ == "__main__":
    unittest.main()
