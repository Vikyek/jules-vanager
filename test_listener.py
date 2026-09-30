#!/usr/bin/env python3
"""
Unit tests for jules_listener Stage 2 AGY takeover deduplication and unstuck logic.
"""

import unittest
import time
import datetime
from unittest.mock import patch, MagicMock

# Function under test helper or imported check
from jules_listener import check_jules_api_queries

class TestJulesListenerAGYTakeoverDeduplication(unittest.TestCase):

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
        print(f"DEBUG: last_unstuck={last_unstuck}, ts_str={ts_str}, dt.timestamp()={dt.timestamp()}")
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
