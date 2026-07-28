from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from run_analysis import (
    latest_completed_supabase_run,
    new_participant_ids,
    participant_ids_from_file,
    replace_run_directory,
)


def write_exports(raw_dir: Path, participant_ids: list[str]) -> None:
    raw_dir.mkdir(parents=True)
    with (raw_dir / "youtube_logs_test.jsonl").open("w", encoding="utf-8") as output:
        for participant_id in participant_ids:
            output.write(json.dumps({"participant_id": participant_id}) + "\n")

    for name in ("nasa_90", "nasa_60", "writing_90", "writing_60"):
        with (raw_dir / f"{name}_test.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as output:
            writer = csv.DictWriter(output, fieldnames=["participant_id"])
            writer.writeheader()
            writer.writerows(
                {"participant_id": participant_id}
                for participant_id in participant_ids
            )


class RunAnalysisOverwriteTests(unittest.TestCase):
    def test_empty_csv_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "empty.csv"
            path.write_text("", encoding="utf-8")

            self.assertEqual(participant_ids_from_file(path), set())

    def test_no_new_participant(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / "previous/raw"
            current = root / "current/raw"
            write_exports(previous, ["A001", "A002"])
            write_exports(current, ["A001", "A002"])

            current_ids, previous_ids, added = new_participant_ids(
                sorted(current.iterdir()), previous
            )

            self.assertEqual(current_ids, {"A001", "A002"})
            self.assertEqual(previous_ids, {"A001", "A002"})
            self.assertEqual(added, [])

    def test_new_rows_for_existing_participant_do_not_create_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / "previous/raw"
            current = root / "current/raw"
            write_exports(previous, ["A001"])
            write_exports(current, ["A001", "A001"])

            _, _, added = new_participant_ids(
                sorted(current.iterdir()), previous
            )

            self.assertEqual(added, [])

    def test_new_participant_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / "previous/raw"
            current = root / "current/raw"
            write_exports(previous, ["A001"])
            write_exports(current, ["A001", "A002"])

            _, _, added = new_participant_ids(
                sorted(current.iterdir()), previous
            )

            self.assertEqual(added, ["A002"])

    def test_only_latest_completed_supabase_run_is_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, completed_at, mode, status in (
                ("run_old", "2026-01-01T00:00:00+09:00", "supabase_export", "complete"),
                ("run_local", "2026-03-01T00:00:00+09:00", "local", "complete"),
                ("run_failed", "2026-04-01T00:00:00+09:00", "supabase_export", "failed"),
                ("run_new", "2026-02-01T00:00:00+09:00", "supabase_export", "complete"),
            ):
                run_dir = root / name
                run_dir.mkdir()
                (run_dir / "manifest.json").write_text(
                    json.dumps(
                        {
                            "completed_at": completed_at,
                            "mode": mode,
                            "status": status,
                        }
                    ),
                    encoding="utf-8",
                )

            result = latest_completed_supabase_run(root, root / "run_current")

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result[0].name, "run_new")

    def test_previous_directory_is_replaced_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / "run_previous"
            current = root / "run_current"
            previous.mkdir()
            current.mkdir()
            (previous / "marker.txt").write_text("old", encoding="utf-8")
            (current / "marker.txt").write_text("new", encoding="utf-8")

            result = replace_run_directory(current, previous)

            self.assertEqual(result, previous)
            self.assertEqual(
                (previous / "marker.txt").read_text(encoding="utf-8"), "new"
            )
            self.assertFalse(current.exists())
            self.assertFalse(any(root.glob(".*overwrite_backup*")))


if __name__ == "__main__":
    unittest.main()
