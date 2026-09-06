# 🤖 jules-vanager

Standalone Google Jules API Manager, Listener Daemon, Interactive Curses TUI, and Conky HUD Widget — with Antigravity integration.

`jules-vanager` programmatically interfaces with the Google Jules API (`jules.googleapis.com/v1alpha`), automates PR verification and branch lifecycle management, provides live interactive curses terminal control, and streams real-time status metrics to status bars like `vlfstatus`.

---

## 🚀 Key Components

- **Jules API Manager ([`jules_manager.py`](file:///home/v/Projects/jules-vanager/jules_manager.py))**: Command-line wrapper for session creation, source exploration, activity trajectory inspection, and message dispatch.
- **Listener Daemon ([`jules_listener.py`](file:///home/v/Projects/jules-vanager/jules_listener.py))**: Background service (`jules-listener.service`) continuously monitoring active sessions, running test/syntax checks, auto-merging approved PRs, deleting merged branches, and archiving completed sessions.
- **Interactive TUI ([`jules_tui.py`](file:///home/v/Projects/jules-vanager/jules_tui.py))**: Terminal UI built with Python `curses` featuring non-blocking thread-pool preloading, session priority sorting, unassigned local PR discovery, live activity view, and prompt response modals.
- **Conky HUD Widget ([`jules_hud.py`](file:///home/v/Projects/jules-vanager/jules_hud.py))**: Lightweight ANSI/text HUD status component formatting session metrics (`~/.config/jules-vanager/status.json`) for terminal overlays or status bars (`vlfstatus`).
- **Browser Cookie Extractor ([`jules_cookie_extractor.py`](file:///home/v/Projects/jules-vanager/jules_cookie_extractor.py))**: Automated extraction tool fetching Jules session cookies from Chrome, Brave, and Firefox SQLite databases.

---

## 💻 CLI Command Reference

### `jules-manager` API Commands
```bash
# List all registered repository sources on Google Jules API
jules-manager list-sources

# List active API sessions (pass --include-archived for complete history)
jules-manager list-sessions --include-archived

# Create a new session task
jules-manager create-session --prompt "Fix bug in auth middleware" --repo "paru-wrapper" --branch "fix/auth-bug"

# Inspect activities and step outputs for a session
jules-manager get-activities --session-id <session_id>

# Send a response message to an active session prompt
jules-manager send-message --session-id <session_id> --message "Proceed with proposed fix"

# Archive or unarchive sessions
jules-manager archive-session --session-id <session_id>
jules-manager unarchive-session --session-id <session_id>
```

### `jules-listener` Service Options
```bash
# Execute a single scan, verify PRs/tests, auto-merge, and exit
jules-listener --once

# Run continuous background monitoring daemon
jules-listener --interval 60
```

### `jules-hud` Display Options
```bash
# Output raw text format for vlfstatus / i3bar
jules-hud --format text

# Output ANSI colorized format for terminal HUD
jules-hud --format ansi

# Continuous stream mode with 5s refresh
jules-hud --format ansi --watch --interval 5
```

---

## 🎨 Visual Identity & Curses Theme Matrix

`jules-tui` establishes visual hierarchy using 7 Python `curses` color pairs:

| Pair | Foreground | Background | Usage |
|---|---|---|---|
| **1** | Yellow | Default | Primary UI text, session prompts, labels |
| **2** | Green | Default | Completed state badges (`SUCCEEDED`, `MERGED`, `COMPLETED`) |
| **3** | Red | Default | Active error indicators, feedback warnings, `PR_CHECK_FAIL` |
| **4** | Red | Yellow | Topbar header normal status bar |
| **5** | Black | Yellow | Active list item selection bar |
| **6** | Black | Red | Critical alert header / Service stopped state |
| **7** | Cyan | Default | Activity logs, prompt replies, web suggestions |

---

## 🛠️ Installation & Setup

### Automated Installation
Run the included idempotent installer script:
```bash
./install.sh
```

### Manual Installation
1. Make all Python executables executable:
   ```bash
   chmod +x jules_manager.py jules_listener.py jules_tui.py jules_hud.py install.sh
   ```
2. Symlink binaries to `~/.local/bin/`:
   ```bash
   ln -sf $PWD/jules_manager.py ~/.local/bin/jules-manager
   ln -sf $PWD/jules_listener.py ~/.local/bin/jules-listener
   ln -sf $PWD/jules_tui.py ~/.local/bin/jules-tui
   ln -sf $PWD/jules_hud.py ~/.local/bin/jules-hud
   ```
3. Deploy Desktop Shortcut & User Systemd Unit:
   ```bash
   cp jules-tui.desktop ~/.local/share/applications/
   cp jules-listener.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   ```

---

## 📜 License

Distributed under the GNU General Public License v3.0 (GPL-3.0). See [`LICENSE`](LICENSE) for details.
