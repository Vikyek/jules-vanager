# 🤖 jules-vanager

Standalone Google Jules API Manager, Listener Daemon, Reactive Textual TUI, and Conky HUD Widget — with Antigravity integration.

`jules-vanager` programmatically interfaces with the Google Jules API (`jules.googleapis.com/v1alpha`), automates PR verification and branch lifecycle management, provides a modern reactive Textual terminal user interface, and streams real-time status metrics to status bars like `vlfstatus`.

---

## 🚀 Key Components

- **Jules API Manager ([`jules_manager.py`](file:///home/v/Projects/jules-vanager/jules_manager.py))**: Command-line wrapper for session creation, source exploration, activity trajectory inspection, and message dispatch.
- **Session Workflow Tool ([`jules_start.py`](file:///home/v/Projects/jules-vanager/jules_start.py))**: CLI launcher (`jules-start`) automatically resolving local directories, git remotes, and branches to start Jules sessions with prompts.
- **Listener Daemon ([`jules_listener.py`](file:///home/v/Projects/jules-vanager/jules_listener.py))**: Background service (`jules-listener.service`) continuously monitoring active sessions, running test/syntax checks, auto-merging approved PRs, deleting merged branches, and archiving completed sessions.
- **Reactive Textual TUI ([`jules_tui.py`](file:///home/v/Projects/jules-vanager/jules_tui.py))**: Modern, reactive terminal UI built with [Textual](https://textual.textualize.io/) (`textual.app.App`, `@work` background thread workers, `ListView`, `Markdown` inspector, `ModalScreen` prompt reply dialogs, and `💡 Panel Suggestions`).
- **Conky HUD Widget ([`jules_hud.py`](file:///home/v/Projects/jules-vanager/jules_hud.py))**: Lightweight ANSI/text HUD status component formatting session metrics (`~/.config/jules-vanager/status.json`) for terminal overlays or status bars (`vlfstatus`).
- **Browser Cookie Extractor ([`jules_cookie_extractor.py`](file:///home/v/Projects/jules-vanager/jules_cookie_extractor.py))**: Automated extraction tool fetching Jules session cookies from Chrome, Brave, and Firefox SQLite databases.

### 🌐 Google Labs Code Ecosystem Integrations (`google-labs-code`)
- **[jules-action](https://github.com/google-labs-code/jules-action)**: GitHub Actions workflows powering automated PR reviews, refactoring, and code quality tasks.
- **[jules-sdk](https://github.com/google-labs-code/jules-sdk)**: Core SDK components for programmatic Jules session orchestration and activity trajectory handling.
- **[jules-skills](https://github.com/google-labs-code/jules-skills)**: Agent skills for automated issue triage, code reviews, and codebase migrations.
- **[jules-awesome-list](https://github.com/google-labs-code/jules-awesome-list)**: Curated prompt templates, strategies, and best practices for Jules AI tasks.
- **[stitch-skills](https://github.com/google-labs-code/stitch-skills)**: Agent skills enabling AI agents to design, build, and iterate UI screens via Stitch MCP tools.
- **[stitch-sdk](https://github.com/google-labs-code/stitch-sdk)**: Programmatic UI screen generation, HTML extraction, and visual screenshot rendering.
- **[stitch-loop](https://github.com/google-labs-code/stitch-loop)**: Iterative design-to-code feedback loop system for real-time UI/UX visual validation.
- **[design.md](https://github.com/google-labs-code/design.md)**: Open-source specification combining YAML design tokens with Markdown rationale for AI design systems.
- **[react-components](https://github.com/google-labs-code/react-components)**: Tools and converters for translating Stitch AI UI designs directly to React components.
- **[shadcn-ui](https://github.com/google-labs-code/shadcn-ui)**: Integration helpers for building accessible component libraries with Tailwind and Radix UI.
- **[enhance-prompt](https://github.com/google-labs-code/enhance-prompt)**: Prompt optimization library transforming simple requests into detailed UI/UX agent instructions.
- **[remotion](https://github.com/google-labs-code/remotion)**: Video generation tools creating animated walkthrough videos from Stitch application designs.

---

## ⚡ Task Offloading Workflow (`jules-start`)

Start a Google Jules session in any target project directly from the CLI or within agent workflows:

```bash
# 1. From within any target project repository:
jules-start "Fix memory leak in background worker and add unit tests"

# 2. Specifying project by repo name, folder path, or owner/repo:
jules-start paru-wrapper "Implement quiet flag for pacman output"
jules-start ~/Projects/agv-dispatcher "Add health-check endpoint"

# 3. With branch override, prompt file, or browser opening:
jules-start -p my-repo -f task_spec.md --branch develop --open

# 4. Dry-run resolution preview:
jules-start jules-vanager "Test prompt" --dry-run
```

---

## 💻 Interactive TUI Keybindings (`jules-tui`)

| Binding | Action | Description |
|---|---|---|
| `Enter` | Reply / Inspect | Open prompt reply modal with Jules' question for active session |
| `r` | Refresh | Trigger async background data refresh |
| `a` | Archive / Unarchive | Toggle archive status for highlighted session |
| `m` | Filter Mode | Cycle session filter mode (`ALL` → `ACTIVE` → `AWAITING` → `FAILED` → `COMPLETED`) |
| `s` | Toggle Service | Start/Stop systemd user listener service |
| `b` | Toggle Autostart | Enable/Disable systemd listener service autostart |
| `w` | Web UI | Launch session URL in browser (`https://jules.google.com`) |
| `p` | Open PR | Open associated GitHub PR in browser |
| `q` | Quit | Clean exit |

### Modal Actions (`ReplyModalScreen`)
- Displays Jules' question / feedback prompt directly when awaiting feedback.
- **`[Enter]` / `Submit`**: Confirm and send prompt response.
- **`[Esc]` / `Cancel`**: Dismiss prompt response modal without sending.

---

## 🛠️ Installation & Dependencies

### Prerequisites
Install project Python dependencies (`textual>=0.50.0`, `requests`):
```bash
pip install -r requirements.txt
```

### Automated Installation
Run the included idempotent installer script:
```bash
./install.sh
```

### Headless Verification Tests
Run non-interactive pilot unit tests for the TUI:
```bash
python3 -m unittest test_tui.py
```

---

## 📜 License

Distributed under the GNU General Public License v3.0 (GPL-3.0). See [`LICENSE`](LICENSE) for details.
