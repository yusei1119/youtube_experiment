import unittest

from scripts.export.export_supabase_logs import enrich_logs_with_session_timing


class ExportSupabaseLogsTests(unittest.TestCase):
    def test_enriches_log_with_measured_session_timestamps(self):
        logs = [{"session_id": "session-1", "event_type": "play"}]
        sessions = [
            {
                "id": "session-1",
                "started_at": "2026-07-31T00:00:00+00:00",
                "expires_at": "2026-07-31T00:05:00+00:00",
                "finished_at": "2026-07-31T00:05:00+00:00",
            }
        ]

        enriched = enrich_logs_with_session_timing(logs, sessions)

        self.assertEqual(
            enriched[0]["session_started_at"],
            "2026-07-31T00:00:00+00:00",
        )
        self.assertEqual(
            enriched[0]["session_finished_at"],
            "2026-07-31T00:05:00+00:00",
        )
        self.assertNotIn("session_started_at", logs[0])


if __name__ == "__main__":
    unittest.main()
