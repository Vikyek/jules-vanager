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

            # Verify binding description updated in app bindings & footer keys
            b_desc = next(b.description for b in app.BINDINGS if getattr(b, "key", "") == "a")
            self.assertEqual(b_desc, "Unarchive")

            # Press 'v' to toggle back
            await pilot.press("v")
            self.assertFalse(app.show_archived)
            b_desc = next(b.description for b in app.BINDINGS if getattr(b, "key", "") == "a")
            self.assertEqual(b_desc, "Archive")

    async def test_modal_screen_rendering(self):
        app = JulesTUIApp()
        async with app.run_test() as pilot:
            # Push modal screen non-interactively
            modal = ReplyModalScreen("test-session-123", "Fix auth middleware bug")
            app.push_screen(modal)
            await pilot.pause()

            # Verify modal components mounted
            self.assertTrue(isinstance(app.screen, ReplyModalScreen))
            self.assertEqual(modal.session_id, "test-session-123")

            # Pop screen to dismiss modal
            app.pop_screen()
            await pilot.pause()

            # Verify return to main screen
            self.assertFalse(isinstance(app.screen, ReplyModalScreen))

if __name__ == "__main__":
    unittest.main()
