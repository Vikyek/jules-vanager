#!/usr/bin/env python3
"""
jules-start: Start a Google Jules coding session in target project with provided prompt.

Usage:
  jules-start [TARGET_PROJECT] "<PROMPT>"
  jules-start "<PROMPT>"                     # Uses current working directory as target project
  jules-start -p <PROJECT> -f <PROMPT_FILE>  # Reads prompt from file
  jules-start --open "<PROMPT>"              # Opens Jules web UI after session creation
"""

import sys
import os

# Add script directory to sys.path to import jules_manager
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from jules_manager import main

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or (len(args) == 1 and args[0] in ("-h", "--help")):
        sys.argv = [sys.argv[0], "start", "--help"]
    else:
        sys.argv = [sys.argv[0], "start"] + args
    main()
