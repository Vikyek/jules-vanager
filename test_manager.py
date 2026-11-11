#!/usr/bin/env python3
"""
Unit tests for jules_manager credentials and request validation.
"""

import unittest
from unittest.mock import patch
from jules_manager import _make_request

class TestJulesManagerCredentials(unittest.TestCase):

    @patch("jules_manager.load_credentials", return_value="ctx7sk_invalid_test_key")
    def test_context7_key_guard(self, mock_cred):
        res = _make_request("sources")
        self.assertIn("error", res)
        self.assertIn("Context7", res["error"])

    @patch("jules_manager.load_credentials", return_value="")
    def test_missing_key_guard(self, mock_cred):
        res = _make_request("sources")
        self.assertIn("error", res)
        self.assertIn("not configured", res["error"])

if __name__ == "__main__":
    unittest.main()
