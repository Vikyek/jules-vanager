#!/usr/bin/env python3
"""
Unit tests for jules_listener Stage 2 AGY takeover deduplication and unstuck logic.
"""

import unittest
import time
import datetime
from unittest.mock import patch, MagicMock

# Function under test helper or imported check
from jules_listener import check_jules_api_queries, auto_spawn_suggestions_queue

class TestAutoSpawnSuggestionsQueue(unittest.TestCase):

    @patch("jules_listener.list_sessions")
    @patch("jules_scraper.fetch_jules_suggestions")
    @patch("jules_scraper.dismiss_suggestion")
    @patch("jules_manager.start_session_workflow")
    def test_auto_spawn_success_dismisses_suggestion(
        self, mock_start_workflow, mock_dismiss, mock_fetch_sugs, mock_list_sessions
    ):
        mock_list_sessions.return_value = {
            "sessions": [{"name": "sessions/active-1", "state": "IN_PROGRESS"}]
        }
        mock_fetch_sugs.return_value = [
            {"title": "Refactor CLI parser", "repo": "Vikyek/jules-vanager", "details": "Clean up argparse"}
        ]
        mock_start_workflow.return_value = {"id": "session-auto-999"}

        sid = auto_spawn_suggestions_queue()

        self.assertEqual(sid, "session-auto-999")
        mock_start_workflow.assert_called_once_with("jules-vanager", "Clean up argparse")
        mock_dismiss.assert_called_once_with("Refactor CLI parser")

    @patch("jules_listener.list_sessions")
    @patch("jules_scraper.fetch_jules_suggestions")
    @patch("jules_scraper.dismiss_suggestion")
    @patch("jules_manager.start_session_workflow")
    def test_auto_spawn_failure_does_not_dismiss_suggestion(
        self, mock_start_workflow, mock_dismiss, mock_fetch_sugs, mock_list_sessions
    ):
        mock_list_sessions.return_value = {
            "sessions": [{"name": "sessions/active-1", "state": "IN_PROGRESS"}]
        }
        mock_fetch_sugs.return_value = [
            {"title": "Fix memory leak", "repo": "paru-wrapper", "details": "Fix buffer issue"}
        ]
        mock_start_workflow.return_value = {"error": "API limit reached"}

        sid = auto_spawn_suggestions_queue()

        self.assertIsNone(sid)
        mock_start_workflow.assert_called_once_with("paru-wrapper", "Fix buffer issue")
        mock_dismiss.assert_not_called()

    @patch("jules_listener.list_sessions")
    @patch("jules_scraper.fetch_jules_suggestions")
    def test_auto_spawn_skipped_when_active_load_high(self, mock_fetch_sugs, mock_list_sessions):
        mock_list_sessions.return_value = {
            "sessions": [
                {"name": "sessions/s1", "state": "IN_PROGRESS"},
                {"name": "sessions/s2", "state": "WORKING"},
                {"name": "sessions/s3", "state": "AWAITING_INPUT"}
            ]
        }

        sid = auto_spawn_suggestions_queue()

        self.assertIsNone(sid)
        mock_fetch_sugs.assert_not_called()

    @patch("jules_listener.list_sessions")
    @patch("jules_scraper.fetch_jules_suggestions")
    def test_auto_spawn_returns_none_on_empty_suggestions(self, mock_fetch_sugs, mock_list_sessions):
        mock_list_sessions.return_value = {"sessions": []}
        mock_fetch_sugs.return_value = []

        sid = auto_spawn_suggestions_queue()

        self.assertIsNone(sid)


if __name__ == "__main__":
    unittest.main()


    @patch("jules_listener.list_sessions")
    @patch("jules_listener.get_session_activities")
    @patch("jules_manager.log_action")
    @patch("jules_manager.archive_session")
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_stage2_agy_takeover_deduplication(
        self, mock_exists, mock_subproc, mock_archive, mock_log_action, mock_activities, mock_list_sessions
    ):
        now = time.time()
        last_unstuck = now - 200  # 200 seconds ago (>180s timeout)
        last_act = now - 250      # inactive before unstuck

        mock_list_sessions.return_value = {
            "sessions": [
                {
                    "name": "sessions/test-session-dedup",
                    "state": "IN_PROGRESS",
                    "prompt": "Test prompt",
                    "sourceContext": {
                        "source": "sources/github/owner/repo",
                        "githubRepoContext": {"startingBranch": "feature-branch"}
                    }
                }
            ]
        }

        mock_activities.return_value = {
            "activities": [
                {"createTime": datetime.datetime.fromtimestamp(last_act, tz=datetime.timezone.utc).isoformat()}
            ]
        }

        # Case 1: No prior AGY_DISPATCH event -> Should execute AGY_DISPATCH
        actions_log_no_dispatch = {
            "test-session-dedup": [
                {"action": "UNSTUCK_PROMPT", "timestamp_epoch": last_unstuck}
            ]
        }

        with patch("builtins.open", unittest.mock.mock_open(read_data='{}')), \
             patch("json.load", return_value=actions_log_no_dispatch):
            check_jules_api_queries()

        mock_log_action.assert_called_with(
            "test-session-dedup", "AGY_DISPATCH", "Dispatched stuck session test-session-dedup to AGY worker",
            title="Test prompt", repo="owner/repo", branch="feature-branch", action_by="auto"
        )
        mock_archive.assert_called_once()
        mock_log_action.reset_mock()
        mock_archive.reset_mock()

        # Case 2: AGY_DISPATCH already recorded for current unstuck attempt -> Should NOT execute AGY_DISPATCH again
        actions_log_with_dispatch = {
            "test-session-dedup": [
                {"action": "UNSTUCK_PROMPT", "timestamp_epoch": last_unstuck},
                {"action": "AGY_DISPATCH", "timestamp_epoch": last_unstuck + 5}
            ]
        }

        with patch("builtins.open", unittest.mock.mock_open(read_data='{}')), \
             patch("json.load", return_value=actions_log_with_dispatch):
            check_jules_api_queries()

        mock_log_action.assert_not_called()
        mock_archive.assert_not_called()

        # Case 3: Prior AGY_DISPATCH was from an OLDER unstuck attempt (ev_time < last_unstuck) -> Should execute AGY_DISPATCH
        actions_log_old_dispatch = {
            "test-session-dedup": [
                {"action": "UNSTUCK_PROMPT", "timestamp_epoch": last_unstuck - 500},
                {"action": "AGY_DISPATCH", "timestamp_epoch": last_unstuck - 495},
                {"action": "UNSTUCK_PROMPT", "timestamp_epoch": last_unstuck}
            ]
        }

        with patch("builtins.open", unittest.mock.mock_open(read_data='{}')), \
             patch("json.load", return_value=actions_log_old_dispatch):
            check_jules_api_queries()

        mock_log_action.assert_called_once_with(
            "test-session-dedup", "AGY_DISPATCH", "Dispatched stuck session test-session-dedup to AGY worker",
            title="Test prompt", repo="owner/repo", branch="feature-branch", action_by="auto"
        )
        mock_archive.assert_called_once()
        mock_log_action.reset_mock()
        mock_archive.reset_mock()

        ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_unstuck + 60))
        dt = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        actions_log_string_ts = {
            "test-session-dedup": [
                {"action": "UNSTUCK_PROMPT", "timestamp_epoch": last_unstuck},
                {"action": "AGY_DISPATCH", "timestamp": ts_str}
            ]
        }

        with patch("builtins.open", unittest.mock.mock_open(read_data='{}')), \
             patch("json.load", return_value=actions_log_string_ts):
            check_jules_api_queries()

        mock_log_action.assert_not_called()
        mock_archive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
