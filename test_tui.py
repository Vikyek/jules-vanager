#!/usr/bin/env python3
"""
Headless pilot verification tests for JulesTUIApp (test_tui.py).
Tests keybindings, list navigation, filter cycling, and modal screen rendering non-interactively.
"""

import unittest
import asyncio
from jules_tui import JulesTUIApp, ReplyModalScreen, SessionItem

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

if __name__ == "__main__":
    unittest.main()
