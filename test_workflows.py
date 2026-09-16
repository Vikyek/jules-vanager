#!/usr/bin/env python3
"""
Unit tests for GitHub Actions workflow definitions in jules-vanager.
Verifies syntax validity and rules (e.g. aur-release workflow triggers strictly on release tag push).
"""

import glob
import os
import unittest
import yaml

WORKFLOWS_DIR = os.path.join(os.path.dirname(__file__), ".github", "workflows")

class TestGitHubWorkflows(unittest.TestCase):

    def test_workflow_yaml_syntax(self):
        """Verifies that all workflow files in .github/workflows are valid YAML."""
        yml_files = glob.glob(os.path.join(WORKFLOWS_DIR, "*.yml")) + glob.glob(os.path.join(WORKFLOWS_DIR, "*.yaml"))
        self.assertGreater(len(yml_files), 0, "No workflow YAML files found.")
        for filepath in yml_files:
            with self.subTest(file=os.path.basename(filepath)):
                with open(filepath, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    self.assertIsInstance(content, dict, f"{filepath} did not parse as a dictionary.")
                    self.assertIn("name", content, f"{filepath} missing 'name' key.")
                    self.assertTrue("on" in content or True in content, f"{filepath} missing 'on' key.")

    def test_aur_release_trigger_tags_only(self):
        """Regression test: aur-release.yml must run ONLY on release tag pushes and not contain invalid pull_request.tags filters."""
        aur_yml = os.path.join(WORKFLOWS_DIR, "aur-release.yml")
        self.assertTrue(os.path.exists(aur_yml), "aur-release.yml not found.")
        
        with open(aur_yml, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        on_section = data.get("on") if "on" in data else data.get(True, {})
        self.assertIn("push", on_section, "aur-release.yml should have 'push' trigger.")
        self.assertIn("tags", on_section["push"], "aur-release.yml 'push' trigger must specify 'tags'.")
        self.assertEqual(on_section["push"]["tags"], ["v*.*.*"], "aur-release.yml push tags filter should be ['v*.*.*'].")

        # GitHub Actions pull_request event does NOT support tags filter
        if "pull_request" in on_section:
            pr_section = on_section["pull_request"]
            if isinstance(pr_section, dict):
                self.assertNotIn("tags", pr_section, "GitHub Actions 'pull_request' trigger does not support 'tags' key.")
        
        # Ensure pull_request is omitted entirely when workflow is meant strictly for release tag pushes
        self.assertNotIn("pull_request", on_section, "aur-release.yml should not trigger on pull_request.")

if __name__ == "__main__":
    unittest.main()
