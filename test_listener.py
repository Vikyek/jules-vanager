#!/usr/bin/env python3
"""
Unit tests for jules_listener including auto-spawn queue and AGY takeover/resolution logic.
"""

import unittest
import time
import datetime
import subprocess
from unittest.mock import patch, MagicMock

import jules_listener
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


class TestJulesListenerAGY(unittest.TestCase):
    @patch('jules_listener.list_sessions')
    @patch('jules_listener.get_session_activities')
    @patch('jules_listener.subprocess.run')
    @patch('jules_listener.send_message')
    @patch('jules_manager.log_action')
    def test_agy_subagent_normal_response(self, mock_log_action, mock_send_message, mock_run, mock_get_activities, mock_list_sessions):
        mock_list_sessions.return_value = {
            "sessions": [{
                "name": "sessions/123",
                "state": "AWAITING_USER_FEEDBACK",
                "prompt": "Fix something"
            }]
        }
        mock_get_activities.return_value = {"activities": [{
            "type": "MESSAGE",
            "agentMessage": {"text": "How should I do this?"}
        }]}

        mock_run.return_value = MagicMock(returncode=0, stdout="Use exactly this code.", stderr="")
        mock_send_message.return_value = {"status": "ok"}

        queries = jules_listener.check_jules_api_queries()

        mock_run.assert_called_once()
        mock_send_message.assert_called_once_with("123", "Use exactly this code.")
        self.assertEqual(len(queries), 0)

    @patch('jules_listener.list_sessions')
    @patch('jules_listener.get_session_activities')
    @patch('jules_listener.subprocess.run')
    @patch('jules_listener.send_message')
    @patch('jules_manager.log_action')
    def test_agy_subagent_wrapped_markdown_response(self, mock_log_action, mock_send_message, mock_run, mock_get_activities, mock_list_sessions):
        mock_list_sessions.return_value = {
            "sessions": [{
                "name": "sessions/123",
                "state": "AWAITING_USER_FEEDBACK",
                "prompt": "Fix something"
            }]
        }
        mock_get_activities.return_value = {"activities": [{
            "type": "MESSAGE",
            "agentMessage": {"text": "How should I do this?"}
        }]}

        mock_run.return_value = MagicMock(returncode=0, stdout="```markdown\nUse exactly this code.\n```", stderr="")
        mock_send_message.return_value = {"status": "ok"}

        queries = jules_listener.check_jules_api_queries()

        mock_run.assert_called_once()
        mock_send_message.assert_called_once_with("123", "Use exactly this code.")
        self.assertEqual(len(queries), 0)

    @patch('jules_listener.list_sessions')
    @patch('jules_listener.get_session_activities')
    @patch('jules_listener.subprocess.run')
    @patch('jules_listener.send_message')
    @patch('jules_manager.log_action')
    def test_agy_subagent_nonzero_exit(self, mock_log_action, mock_send_message, mock_run, mock_get_activities, mock_list_sessions):
        mock_list_sessions.return_value = {
            "sessions": [{
                "name": "sessions/123",
                "state": "AWAITING_USER_FEEDBACK",
                "prompt": "Fix something"
            }]
        }
        mock_get_activities.return_value = {"activities": [{
            "type": "MESSAGE",
            "agentMessage": {"text": "How should I do this?"}
        }]}

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Command failed")

        queries = jules_listener.check_jules_api_queries()

        mock_run.assert_called_once()
        mock_send_message.assert_not_called()
        self.assertEqual(len(queries), 1)

    @patch('jules_listener.list_sessions')
    @patch('jules_listener.get_session_activities')
    @patch('jules_listener.subprocess.run')
    @patch('jules_listener.send_message')
    @patch('jules_manager.log_action')
    def test_agy_subagent_timeout(self, mock_log_action, mock_send_message, mock_run, mock_get_activities, mock_list_sessions):
        mock_list_sessions.return_value = {
            "sessions": [{
                "name": "sessions/123",
                "state": "AWAITING_USER_FEEDBACK",
                "prompt": "Fix something"
            }]
        }
        mock_get_activities.return_value = {"activities": [{
            "type": "MESSAGE",
            "agentMessage": {"text": "How should I do this?"}
        }]}

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="agy", timeout=90)

        queries = jules_listener.check_jules_api_queries()

        mock_run.assert_called_once()
        mock_send_message.assert_not_called()
        self.assertEqual(len(queries), 1)

if __name__ == "__main__":
    unittest.main()
