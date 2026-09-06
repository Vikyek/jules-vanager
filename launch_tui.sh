#!/bin/bash
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-/run/user/1001/lyxauth}"
cd /home/v/Projects/jules-vanager
python3 /home/v/Projects/jules-vanager/jules_tui.py
status=$?
if [ $status -ne 0 ]; then
    echo "jules_tui exited with status $status"
    read -p "Press Enter to exit..."
fi
