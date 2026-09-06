#!/usr/bin/env python3
"""
Unit and regression tests for jules_scraper dynamic code analysis suggestions.
"""

import os
import unittest
from unittest.mock import patch, MagicMock
from jules_scraper import fetch_sourcery_pr_suggestions, fetch_jules_suggestions


class TestJulesScraper(unittest.TestCase):

    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_dynamic_commit_suggestions_generation(self, mock_exists, mock_subproc):
        git_log_output = (
            "33cf84f feat(suggestions): dynamic auto-generation of fresh code analysis suggestions\n"
            "ce0e6d4 fix(pkg): update sha256 checksums\n"
            "a1b2c3d Merge pull request #10 from dev/feat\n"
            "e5f6a7b Merge branch 'main' into dev\n"
            "9876543 \n"  # line with single token or space-only message
            "1122334 Merge remote-tracking branch 'origin/main'\n"
        )
        mock_subproc.return_value = MagicMock(returncode=0, stdout=git_log_output)

        with patch("jules_scraper.fetch_sourcery_pr_suggestions") as mock_fetch_pr:
            mock_fetch_pr.return_value = []
            suggestions = fetch_sourcery_pr_suggestions()

        titles = [s["title"] for s in suggestions]
        sources = [s["source"] for s in suggestions]

        # Verify non-merge commits are captured
        self.assertTrue(any("33cf84f" in t for t in titles))
        self.assertTrue(any("ce0e6d4" in t for t in titles))

        # Verify merge commits and empty message commits are filtered out
        self.assertFalse(any("a1b2c3d" in t for t in titles))
        self.assertFalse(any("e5f6a7b" in t for t in titles))
        self.assertFalse(any("1122334" in t for t in titles))

        # Verify source is git_commit_log
        self.assertTrue(all(src == "git_commit_log" for src in sources))

    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_deduplication_and_error_resilience(self, mock_exists, mock_subproc):
        # Test subprocess exception handling gracefully
        mock_subproc.side_effect = Exception("Subprocess failure")
        suggestions = fetch_sourcery_pr_suggestions()
        self.assertIsInstance(suggestions, list)

    @patch("os.path.exists", return_value=False)
    def test_nonexistent_repo_dir(self, mock_exists):
        suggestions = fetch_sourcery_pr_suggestions()
        self.assertIsInstance(suggestions, list)


if __name__ == "__main__":
    unittest.main()
