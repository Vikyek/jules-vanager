from unittest.mock import patch, ANY
#!/usr/bin/env python3
"""
Headless pilot verification tests for JulesTUIApp (test_tui.py).
Tests keybindings, list navigation, filter cycling, and modal screen rendering non-interactively.
"""

import unittest
import asyncio
from jules_tui import JulesTUIApp, ReplyModalScreen, SessionItem
from textual.widgets import TextArea

class TestJulesTUIApp(unittest.IsolatedAsyncioTestCase):

    async def test_app_lifecycle_and_bindings(self):
        app = JulesTUIApp()
        async with app.run_test() as pilot:
            # Verify initial render and header title
            self.assertEqual(app.TITLE, "Jules Vanager TUI")
            self.assertTrue(pilot.app.is_running)

            # Test filter mode cycling binding ('m')
            initial_filter = app.filter_mode
            await pilot.press("m")
            self.assertNotEqual(app.filter_mode, initial_filter)
            self.assertEqual(app.filter_mode, "ACTIVE")

            await pilot.press("m")
            self.assertEqual(app.filter_mode, "AWAITING")

            await pilot.press("m")
            self.assertEqual(app.filter_mode, "FAILED")

            await pilot.press("m")
            self.assertEqual(app.filter_mode, "COMPLETED")

            await pilot.press("m")
            self.assertEqual(app.filter_mode, "ALL")
            await pilot.exit(0)

    async def test_archive_toggle_footer_binding(self):
        app = JulesTUIApp()
        async with app.run_test() as pilot:
            self.assertFalse(app.show_archived)
            # Press 'v' to toggle archived view
            await pilot.press("v")
            self.assertTrue(app.show_archived)

            # Verify dynamic action label
            _, label = app.check_action_archive_selected()
            self.assertEqual(label, "Unarchive")

            # Press 'v' to toggle back
            await pilot.press("v")
            self.assertFalse(app.show_archived)
            _, label = app.check_action_archive_selected()
            self.assertEqual(label, "Archive")
            await pilot.exit(0)

    async def test_modal_screen_rendering(self):
        app = JulesTUIApp()
        async with app.run_test() as pilot:
            # Push modal screen non-interactively with long question
            long_question = "Question line\n" * 30
            modal = ReplyModalScreen("test-session-123", "Fix auth middleware bug", question=long_question)
            app.push_screen(modal)
            await pilot.pause()

            # Verify modal components mounted
            self.assertTrue(isinstance(app.screen, ReplyModalScreen))
            self.assertEqual(modal.session_id, "test-session-123")

            # Test scrolling actions
            modal.action_scroll_down()
            await pilot.pause()
            modal.action_scroll_up()
            await pilot.pause()

            # Pop screen to dismiss modal
            app.pop_screen()
            await pilot.pause()

            # Verify return to main screen
            self.assertFalse(isinstance(app.screen, ReplyModalScreen))
            await pilot.exit(0)

    async def test_reply_modal_multiline_submission(self):
        app = JulesTUIApp()
        async with app.run_test() as pilot:
            result_container = []
            modal = ReplyModalScreen("test-session-123", "Fix auth middleware bug", question="Details?")
            app.push_screen(modal, callback=lambda val: result_container.append(val))
            await pilot.pause()

            # Verify TextArea present and focused
            text_area = modal.query_one(TextArea)
            self.assertIsNotNone(text_area)
            self.assertEqual(modal.focused, text_area)

            # Insert multiline text
            text_area.text = "First line of reply\nSecond line with code\nThird line done"
            modal.action_submit_reply()
            await pilot.pause()

            # Verify callback received multiline text
            self.assertEqual(result_container, ["First line of reply\nSecond line with code\nThird line done"])
            await pilot.exit(0)

    async def test_answering_badge_and_state(self):
        app = JulesTUIApp()
        app.sessions = [
            {"id": "test-sid-999", "state": "AWAITING_USER_FEEDBACK", "title": "Awaiting session"}
        ]
        async with app.run_test() as pilot:
            app.populate_session_list()
            await pilot.pause()

            # Mark session as answering
            app.mark_session_answering("test-sid-999")
            self.assertIn("test-sid-999", app.answering_sessions)

            # Trigger animation frame
            app.animate_status_bar()
            await pilot.pause()

            # Clear answering status
            app.clear_session_answering("test-sid-999")
            self.assertNotIn("test-sid-999", app.answering_sessions)
            await pilot.exit(0)

    async def test_suggestions_panel_toggle_and_cycling(self):
        app = JulesTUIApp()
        app.suggestions = [
            {"title": "Audit auth module", "details": "Fix potential timing attack", "repo": "Vikyek/paru-wrapper"}
        ]
        async with app.run_test() as pilot:
            self.assertFalse(app.show_suggestions)
            # Toggle suggestions view ('g')
            await pilot.press("g")
            self.assertTrue(app.show_suggestions)
            self.assertFalse(app.show_archived)

            # Cycle filter mode ('m') should reset suggestions view
            await pilot.press("m")
            self.assertFalse(app.show_suggestions)
            self.assertEqual(app.filter_mode, "ACTIVE")

            # Toggle suggestions view back on
            await pilot.press("g")
            self.assertTrue(app.show_suggestions)

            # Toggle archive panel ('v') should disable suggestions view
            await pilot.press("v")
            self.assertFalse(app.show_suggestions)
            self.assertTrue(app.show_archived)

            await pilot.exit(0)

class TestPanelSuggestionsAndDirectSpawning(unittest.IsolatedAsyncioTestCase):

    def test_inspect_reply_on_suggestion_spawns_worker_without_modal(self):
        """Verify action_inspect_reply directly spawns worker and dismisses suggestion without pushing modal screen."""
        from unittest.mock import patch, MagicMock
        from textual.widgets import ListView

        app = JulesTUIApp()
        app.suggestions = [
            {"title": "Optimize DB queries", "repo": "Vikyek/jules-manager", "details": "Add index", "is_suggestion": True}
        ]

        suggestion_item = SessionItem({"title": "Optimize DB queries", "repo": "Vikyek/jules-manager", "details": "Add index", "is_suggestion": True})
        list_view = MagicMock(spec=ListView)
        list_view.highlighted_child = suggestion_item

        with patch.object(app, "query_one", return_value=list_view), \
             patch("jules_tui.dismiss_suggestion") as mock_dismiss, \
             patch.object(app, "spawn_suggestion_worker") as mock_spawn, \
             patch.object(app, "push_screen") as mock_push_screen:

            app.action_inspect_reply()

            # Verify auto-dismissal and session spawning triggered
            mock_dismiss.assert_called_once_with("Optimize DB queries")
            mock_spawn.assert_called_once_with("Vikyek/jules-manager", "Add index", "Optimize DB queries")
            
            # Verify no reply modal screen was pushed
            mock_push_screen.assert_not_called()

    async def test_fetch_activities_worker_skips_suggestions_and_agy(self):
        """Verify fetch_session_activities_worker returns early for suggestions and AGY stolen sessions."""
        from unittest.mock import patch

        app = JulesTUIApp()
        async with app.run_test() as pilot:
            with patch("jules_tui.get_session_activities") as mock_get_act:
                app.fetch_session_activities_worker("sug-12345", {"is_suggestion": True}, "N/A")
                app.fetch_session_activities_worker("agy-67890", {"is_agy_stolen": True}, "N/A")
                app.fetch_session_activities_worker("pr-111", {"is_unassigned_pr": True}, "N/A")
                mock_get_act.assert_not_called()


class TestSessionBadgeRendering(unittest.IsolatedAsyncioTestCase):
    """Regression tests for session badge icon mappings and rich hex styling (commit 04e121f)."""

    async def test_session_badge_icons_and_styling(self):
        app = JulesTUIApp()
        test_cases = [
            ("SUGGESTION", "[💡 SUGGESTION]", "bold #eab308"),
            ("UNASSIGNED_PR", "[🐙 UNASSIGNED PR]", "bold #c084fc"),
            ("UNSTUCK_PROMPT", "[⚡ UNSTUCK NUDGE]", "bold #f97316"),
            ("UNSTUCK", "[⚡ UNSTUCK NUDGE]", "bold #f97316"),
            ("AGY_DISPATCH", "[🤖 AGY TAKEOVER]", "bold #ec4899"),
            ("AWAITING_USER_FEEDBACK", "[❓ AWAITING INPUT]", "bold #f59e0b"),
            ("PAUSED", "[❓ PAUSED]", "bold #f59e0b"),
            ("AWAITING_INPUT", "[❓ AWAITING_INPUT]", "bold #f59e0b"),
            ("IN_PROGRESS", "[⚙️ RUNNING]", "bold #3b82f6"),
            ("RUNNING", "[⚙️ RUNNING]", "bold #3b82f6"),
            ("COMPLETED", "[✔ COMPLETED]", "bold #22c55e"),
            ("SUCCEEDED", "[✔ COMPLETED]", "bold #22c55e"),
            ("RESOLVED", "[✔ COMPLETED]", "bold #22c55e"),
            ("MERGED", "[✔ COMPLETED]", "bold #22c55e"),
            ("FAILED", "[✖ FAILED]", "bold #ef4444"),
            ("PR_CONFLICT", "[✖ PR_CONFLICT]", "bold #ef4444"),
            ("REJECTED", "[✖ REJECTED]", "bold #ef4444"),
            ("ERROR", "[✖ ERROR]", "bold #ef4444"),
            ("UNKNOWN_STATE", "[UNKNOWN_STATE]", "#71717a"),
        ]

        async with app.run_test() as pilot:
            from textual.widgets import Static
            for state, expected_badge, expected_style in test_cases:
                item = SessionItem({"id": f"sid-{state}", "state": state, "title": f"Test {state}"})

                await app.mount(item)

                static = item.query_one("#item-static", Static)
                item.update_rendering()
                rendered_text = static.render()

                full_plain = rendered_text.plain
                self.assertTrue(full_plain.startswith(expected_badge), f"Expected {expected_badge} in {full_plain} for state {state}")

                badge_span_style = str(rendered_text.spans[0].style)

                expected_parsed = []
                for p in expected_style.split():
                    if p.startswith('#'):
                        hex_val = p[1:]
                        expected_parsed.append(f"rgb({int(hex_val[0:2], 16)},{int(hex_val[2:4], 16)},{int(hex_val[4:6], 16)})")
                    else:
                        expected_parsed.append(p)
                actual_sorted = " ".join(sorted(badge_span_style.split()))
                expected_sorted = " ".join(sorted(expected_parsed))
                self.assertEqual(actual_sorted, expected_sorted, f"State {state} expected style {expected_style}, got {badge_span_style}")

class TestScraperCommitFiltering(unittest.TestCase):



    def test_deduplicate_and_filter_merge_commits(self):
        from jules_scraper import fetch_jules_suggestions
        from unittest.mock import patch
        import tempfile
        import os
        import json

        # Mock persistent suggestions containing duplicates and merge commit messages
        mock_suggestions = [
            {"title": "Audit repo (123456): fix(auth): prevent timing attack", "details": "Code health recommendation: fix(auth): prevent timing attack"},
            {"title": "Audit repo (7890ab): fix(auth): prevent timing attack", "details": "Code health recommendation: fix(auth): prevent timing attack"},
            {"title": "Audit repo (abcdef): Merge pull request #42 from dev", "details": "Code health recommendation: Merge pull request #42 from dev"},
            {"title": "Audit repo (fedcba): Merge branch 'main' into feature", "details": "Code health recommendation: Merge branch 'main' into feature"},
        ]

        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as tmp:
            json.dump(mock_suggestions, tmp)
            tmp_path = tmp.name

        import jules_scraper
        orig_scanned_file = jules_scraper.SCANNED_SUGGESTIONS_FILE
        try:
            jules_scraper.SCANNED_SUGGESTIONS_FILE = tmp_path
            with patch("jules_scraper.fetch_sourcery_pr_suggestions", return_value=[]):
                results = fetch_jules_suggestions(raw_html_snippet="<div>custom HTML</div>")
                
                # Verify merge commits filtered out
                titles = [s["title"] for s in results]
                self.assertFalse(any("Merge pull request" in t for t in titles))
                self.assertFalse(any("Merge branch" in t for t in titles))

                # Verify deduplication of mock items (only 1 fix(auth) timing attack suggestion remains)
                fix_auth_items = [s for s in results if "prevent timing attack" in s.get("details", "")]
                self.assertEqual(len(fix_auth_items), 1)
                self.assertIn("123456", fix_auth_items[0]["title"])
        finally:
            jules_scraper.SCANNED_SUGGESTIONS_FILE = orig_scanned_file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestStuckRecoveryPipeline(unittest.TestCase):

    @patch('jules_listener.time.time')
    def test_stage1_unstuck_nudge_trigger(self, mock_time):
        """Test Stage 1 UNSTUCK_PROMPT triggers when inactive for >300s with no previous unstuck attempt."""
        import datetime
        from unittest.mock import patch, ANY
        from jules_listener import check_jules_api_queries

        mock_time.return_value = 1788916200.202408
        now_mock = 1788916200.202408
        past_iso = "2026-09-09T01:03:20.202408Z"


        mock_sessions = {
            "sessions": [
                {
                    "name": "sessions/sess-stuck-1",
                    "state": "IN_PROGRESS",
                    "prompt": "Test stuck task",
                    "sourceContext": {"source": "sources/github/owner/repo"}
                }
            ]
        }
        mock_activities = {
            "activities": [
                {"createTime": past_iso, "agentMessaged": {"agentMessage": "Working..."}}
            ]
        }

        with patch("jules_listener.list_sessions", return_value=mock_sessions), \
             patch("jules_listener.get_session_activities", return_value=mock_activities), \
             patch("jules_listener.send_message", return_value={"status": "ok"}) as mock_send, \
             patch("jules_manager.log_action") as mock_log, \
             patch("os.path.exists", return_value=False):

            check_jules_api_queries()
            mock_send.assert_called_once_with("sess-stuck-1", ANY)
            mock_log.assert_called_once()
            self.assertEqual(mock_log.call_args[0][1], "UNSTUCK_PROMPT")

    def test_stage2_agy_takeover_trigger(self):
        """Test Stage 2 AGY_DISPATCH triggers when Stage 1 attempt timed out (>180s) without progress."""
        import time
        from unittest.mock import patch, ANY
        from jules_listener import check_jules_api_queries

        sys_now = time.time()

        mock_sessions = {
            "sessions": [
                {
                    "name": "sessions/sess-stuck-2",
                    "state": "IN_PROGRESS",
                    "prompt": "Test stuck task stage 2",
                    "sourceContext": {"source": "sources/github/owner/repo"}
                }
            ]
        }
        import datetime
        past_iso = datetime.datetime.fromtimestamp(sys_now - 400, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        mock_activities = {
            "activities": [
                {"createTime": past_iso, "agentMessaged": {"agentMessage": "Old progress"}}
            ]
        }
        mock_actions_log = {
            "sess-stuck-2": [
                {"action": "UNSTUCK_PROMPT", "timestamp_epoch": sys_now - 200}
            ]
        }

        with patch("jules_listener.list_sessions", return_value=mock_sessions), \
             patch("jules_listener.get_session_activities", return_value=mock_activities), \
             patch("jules_listener.send_message") as mock_send, \
             patch("json.load", return_value=mock_actions_log), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data='{}')), \
             patch("subprocess.run") as mock_subproc, \
             patch("jules_manager.archive_session") as mock_archive, \
             patch("jules_manager.log_action") as mock_log, \
             patch("jules_listener.time.time", return_value=sys_now):

            check_jules_api_queries()
            mock_send.assert_not_called()
            mock_log.assert_called_once()
            self.assertEqual(mock_log.call_args[0][1], "AGY_DISPATCH")
            mock_archive.assert_called_once_with("sess-stuck-2", action_by="auto", title="Test stuck task stage 2", repo="owner/repo", branch="main")





class TestSuggestionAutoDismissal(unittest.TestCase):

    def test_auto_dismiss_panel_suggestion_on_spawn(self):
        """Verify suggestion auto-dismisses when spawned into a session (commit 8152dda)."""
        from unittest.mock import patch, MagicMock
        from textual.widgets import ListView

        app = JulesTUIApp()
        app.suggestions = [
            {"title": "Fix auth middleware bug", "repo": "Vikyek/jules-manager", "details": "Fix auth error", "is_suggestion": True},
            {"title": "Add unit test for run_cmd", "repo": "Vikyek/paru-wrapper", "details": "Add test", "is_suggestion": True},
        ]

        suggestion_item = SessionItem(app.suggestions[0])
        event = ListView.Selected(MagicMock(), suggestion_item, 0)

        with patch("jules_tui.dismiss_suggestion") as mock_dismiss, \
             patch.object(app, "spawn_suggestion_worker") as mock_spawn, \
             patch.object(app, "populate_session_list"):

            app.on_list_view_selected(event)

            # Verify dismiss_suggestion was called with the exact title
            mock_dismiss.assert_called_once_with("Fix auth middleware bug")
            
            # Verify suggestion was filtered out from app.suggestions
            remaining_titles = [s.get("title") for s in app.suggestions]
            self.assertNotIn("Fix auth middleware bug", remaining_titles)
            self.assertIn("Add unit test for run_cmd", remaining_titles)

            # Verify spawn_suggestion_worker was invoked
            mock_spawn.assert_called_once_with("Vikyek/jules-manager", "Fix auth error", "Fix auth middleware bug")

    def test_auto_dismiss_handles_edge_cases(self):
        """Verify robust handling of whitespace and None titles in suggestion dictionary during dismissal."""
        from unittest.mock import patch, MagicMock
        from textual.widgets import ListView

        app = JulesTUIApp()
        app.suggestions = [
            {"title": None, "details": "No title suggestion", "is_suggestion": True},
            {"title": "   ", "details": "Blank title suggestion", "is_suggestion": True},
            {"title": " Valid Suggestion ", "details": "Valid details", "is_suggestion": True},
        ]

        # Select valid suggestion with trailing spaces
        suggestion_item = SessionItem({"title": " Valid Suggestion ", "repo": "paru-wrapper", "is_suggestion": True})
        event = ListView.Selected(MagicMock(), suggestion_item, 0)

        with patch("jules_tui.dismiss_suggestion") as mock_dismiss, \
             patch.object(app, "spawn_suggestion_worker"), \
             patch.object(app, "populate_session_list"):

            # Should not raise AttributeError when processing None/whitespace items in app.suggestions
            app.on_list_view_selected(event)
            mock_dismiss.assert_called_once_with(" Valid Suggestion ")
            self.assertEqual(len(app.suggestions), 2)


if __name__ == "__main__":
    unittest.main()




class TestTuiPerformanceTimers(unittest.IsolatedAsyncioTestCase):
    async def test_high_frequency_rendering_tick_and_auto_refresh(self):
        """Regression test for commit 3cc7415 (100ms item render tick and 5s auto-refresh)."""
        app = JulesTUIApp()

        async with app.run_test() as pilot:
            from unittest.mock import patch
            from textual.widgets import ListView
            list_view = app.query_one("#session-list", ListView)

            s_running = SessionItem({"id": "sid-running", "state": "IN_PROGRESS", "title": "Test Running"})
            s_completed = SessionItem({"id": "sid-completed", "state": "COMPLETED", "title": "Test Completed"})

            await list_view.mount(s_running)
            await list_view.mount(s_completed)
            await pilot.pause()

            app.answering_sessions = {"sid-running": 1}

            with patch.object(s_running, "update_rendering") as mock_running_update, \
                 patch.object(s_completed, "update_rendering") as mock_completed_update:

                app.animate_status_bar()

                mock_running_update.assert_called_once()
                mock_completed_update.assert_not_called()

            import time
            app.answering_sessions = {"sid-expired": time.time() - 200, "sid-fresh": time.time() - 10}
            app.animate_status_bar()
            self.assertNotIn("sid-expired", app.answering_sessions)
            self.assertIn("sid-fresh", app.answering_sessions)

            with patch.object(app, "fetch_data_worker") as mock_fetch_worker:
                app.auto_refresh_sessions()
                mock_fetch_worker.assert_called_once()
