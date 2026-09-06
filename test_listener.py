import unittest
from unittest.mock import patch, MagicMock
import subprocess
import jules_listener

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

if __name__ == '__main__':
    unittest.main()
