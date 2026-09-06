#!/usr/bin/env python3
"""
Jules Terminal UI (jules_tui.py)
Modern, reactive Textual TUI application for Google Jules API sessions,
background listener service management, PR status tracking, and prompt replies.
"""

import os
import sys
import json
import time
import subprocess
import webbrowser
import pathlib
from typing import List, Dict, Any, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, Static, ListView, ListItem, Label, Input, Button, Markdown
from textual.worker import Worker, WorkerState
from textual import work

# Import API manager functions
from jules_manager import list_sessions, get_session_activities, send_message, archive_session, _make_request

CONFIG_DIR = pathlib.Path.home() / ".config" / "jules-vanager"
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSIONS_CACHE_FILE = CONFIG_DIR / "sessions_cache.json"
STATUS_FILE = CONFIG_DIR / "status.json"

def load_config() -> Dict[str, Any]:
    default_cfg = {
        "mode": "continuous",
        "interval": 60,
        "agy_mode": "plan",
        "agy_skip_permissions": True
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                loaded = json.load(f)
                default_cfg.update(loaded)
        except Exception:
            pass
    return default_cfg

def save_config(cfg: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def load_cached_sessions() -> List[Dict[str, Any]]:
    if SESSIONS_CACHE_FILE.exists() and SESSIONS_CACHE_FILE.stat().st_size > 0:
        try:
            with open(SESSIONS_CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_cached_sessions(sessions: List[Dict[str, Any]]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(SESSIONS_CACHE_FILE, "w") as f:
        json.dump(sessions, f, indent=2)

def toggle_systemd_service() -> str:
    check = subprocess.run(["systemctl", "--user", "is-active", "jules-listener.service"], capture_output=True, text=True)
    is_active = check.stdout.strip() == "active"
    if is_active:
        subprocess.run(["systemctl", "--user", "stop", "jules-listener.service"], capture_output=True, text=True)
        return "Stopped background listener service."
    else:
        subprocess.run(["systemctl", "--user", "start", "jules-listener.service"], capture_output=True, text=True)
        return "Started background listener service."

def toggle_systemd_autostart() -> str:
    check = subprocess.run(["systemctl", "--user", "is-enabled", "jules-listener.service"], capture_output=True, text=True)
    is_enabled = "enabled" in check.stdout.strip()
    if is_enabled:
        subprocess.run(["systemctl", "--user", "disable", "jules-listener.service"], capture_output=True, text=True)
        return "Disabled system autostart for listener service."
    else:
        subprocess.run(["systemctl", "--user", "enable", "jules-listener.service"], capture_output=True, text=True)
        return "Enabled system autostart for listener service."

_SESSION_PR_STATUS_CACHE = {}
_SESSION_PR_STATUS_CACHE_TIME = {}

def check_session_pr_status(session: Dict[str, Any]) -> Dict[str, Any]:
    default_res = {
        "has_pr": False, "pr_number": None, "status_checks_failing": False,
        "has_review_issues": False, "mergeable": "UNKNOWN", "needs_update": False, "url": ""
    }
    if not session:
        return default_res
    sid = session.get("id") or session.get("name", "").split("/")[-1]
    
    now = time.time()
    if sid in _SESSION_PR_STATUS_CACHE and (now - _SESSION_PR_STATUS_CACHE_TIME.get(sid, 0)) < 45:
        return _SESSION_PR_STATUS_CACHE[sid]

    src_ctx = session.get("sourceContext", {})
    rep_name = src_ctx.get("source", "").replace("sources/github/", "").replace("sources/", "")
    if not rep_name:
        rep_name = "paru-wrapper"
    projects_dir = pathlib.Path.home() / "Projects"
    repo_path = projects_dir / os.path.basename(rep_name)
    if not (repo_path / ".git").exists():
        _SESSION_PR_STATUS_CACHE[sid] = default_res
        _SESSION_PR_STATUS_CACHE_TIME[sid] = now
        return default_res
    try:
        res = subprocess.run(["gh", "pr", "list", "--state", "all", "--json", "number,title,headRefName,url,mergeable,reviewDecision,statusCheckRollup,comments,reviews"], cwd=str(repo_path), capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            prs = json.loads(res.stdout)
            for pr in prs:
                branch = pr.get("headRefName", "")
                title = pr.get("title", "")
                if sid in branch or sid in title or branch.endswith(sid):
                    num = pr.get("number")
                    url = pr.get("url", "")
                    mergeable = pr.get("mergeable", "UNKNOWN")
                    review_decision = pr.get("reviewDecision", "")
                    
                    checks_failing = any(
                        c.get("status") == "COMPLETED" and c.get("conclusion") in ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED")
                        for c in pr.get("statusCheckRollup", [])
                    )
                    has_review_issues = review_decision in ("CHANGES_REQUESTED",) or any("issue" in c.get("body", "").lower() for c in pr.get("comments", []))

                    res_obj = {
                        "has_pr": True,
                        "pr_number": num,
                        "status_checks_failing": checks_failing,
                        "has_review_issues": has_review_issues,
                        "mergeable": mergeable,
                        "needs_update": mergeable in ("CONFLICTING", "BEHIND"),
                        "url": url
                    }
                    _SESSION_PR_STATUS_CACHE[sid] = res_obj
                    _SESSION_PR_STATUS_CACHE_TIME[sid] = now
                    return res_obj
    except Exception:
        pass
    _SESSION_PR_STATUS_CACHE[sid] = default_res
    _SESSION_PR_STATUS_CACHE_TIME[sid] = now
    return default_res

def get_unassigned_jules_prs(active_sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    active_sids = {s.get("id") or s.get("name", "").split("/")[-1] for s in active_sessions}
    unassigned_items = []
    projects_dir = pathlib.Path.home() / "Projects"
    if not projects_dir.exists():
        return unassigned_items

    for repo_path in projects_dir.iterdir():
        if repo_path.is_dir() and (repo_path / ".git").exists():
            try:
                res = subprocess.run(["gh", "pr", "list", "--state", "open", "--json", "number,title,headRefName,url,mergeable,statusCheckRollup,comments,reviews"], cwd=str(repo_path), capture_output=True, text=True, timeout=2)
                if res.returncode == 0:
                    prs = json.loads(res.stdout)
                    for pr in prs:
                        title = pr.get("title", "")
                        branch = pr.get("headRefName", "")
                        num = pr.get("number")
                        url = pr.get("url", "")
                        
                        is_jules = "jules" in branch.lower() or "jules" in title.lower() or title.startswith(("🛡️", "⚡", "🔌", "🌈", "📜", "📦", "🎨", "🧪"))
                        if not is_jules:
                            continue

                        extracted_sid = branch.split("-")[-1] if "-" in branch else ""
                        if extracted_sid in active_sids:
                            continue

                        synthetic_sid = extracted_sid if (extracted_sid and len(extracted_sid) >= 15) else f"pr-{repo_path.name}-{num}"
                        unassigned_items.append({
                            "id": synthetic_sid,
                            "name": f"sessions/{synthetic_sid}",
                            "title": f"[{repo_path.name}] PR #{num}: {title}",
                            "state": "UNASSIGNED_PR",
                            "is_unassigned_pr": True,
                            "pr_number": num,
                            "repo": repo_path.name,
                            "branch": branch,
                            "url": url,
                            "prompt": f"Unassigned Jules PR #{num} in {repo_path.name} ({branch}): {title}\nURL: {url}",
                            "sourceContext": {
                                "source": f"sources/github/Vikyek/{repo_path.name}",
                                "githubRepoContext": {"startingBranch": branch}
                            }
                        })
            except Exception:
                pass
    return unassigned_items


class SessionItem(ListItem):
    """List item displaying session details and state badges."""
    def __init__(self, session: Dict[str, Any]) -> None:
        super().__init__()
        self.session = session
        self.sid = session.get("id") or session.get("name", "").split("/")[-1]

    def compose(self) -> ComposeResult:
        state = self.session.get("state", "UNKNOWN")
        title = self.session.get("title") or self.session.get("prompt") or f"Session {self.sid}"
        if len(title) > 60:
            title = title[:57] + "..."

        from rich.text import Text

        if state in ("COMPLETED", "SUCCEEDED", "RESOLVED", "MERGED"):
            color = "bold green"
        elif "FAIL" in state or "CONFLICT" in state or "REJECTED" in state:
            color = "bold red"
        elif "AWAITING" in state or "IN_PROGRESS" in state or "RUNNING" in state:
            color = "bold yellow"
        else:
            color = "dim white"

        txt = Text()
        txt.append(f"[{state}]", style=color)
        txt.append(f" {title}")
        yield Static(txt, classes="item-title")


class ReplyModalScreen(ModalScreen[Optional[str]]):
    """Modal screen for sending prompt responses to an active session."""
    BINDINGS = [
        Binding("escape", "dismiss_modal", "Cancel", show=True),
    ]

    DEFAULT_CSS = """
    ReplyModalScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #dialog {
        padding: 1 2;
        background: $surface;
        border: thick $primary;
        width: 70;
        height: 18;
    }

    #dialog-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #dialog-prompt {
        color: $text;
        margin-bottom: 1;
        height: 4;
        overflow-y: auto;
    }

    Input {
        margin: 1 0;
    }

    #buttons {
        height: 3;
        align: right middle;
    }

    Button {
        margin-left: 1;
    }
    """

    def __init__(self, session_id: str, prompt_text: str) -> None:
        super().__init__()
        self.session_id = session_id
        self.prompt_text = prompt_text

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label(f"🤖 Reply to Session [{self.session_id}]", id="dialog-title")
            yield Static(f"Prompt: {self.prompt_text}", id="dialog-prompt")
            yield Input(placeholder="Type message reply (or press Enter to Submit)...", id="reply-input")
            with Horizontal(id="buttons"):
                yield Button("Cancel [Esc]", variant="error", id="cancel")
                yield Button("Submit [Enter]", variant="primary", id="submit")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            val = self.query_one(Input).value.strip()
            self.dismiss(val if val else None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        self.dismiss(val if val else None)

class ConfirmModalScreen(ModalScreen[bool]):
    """Modal screen for action confirmation prompts."""
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    DEFAULT_CSS = """
    ConfirmModalScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #confirm-dialog {
        padding: 1 2;
        background: $surface;
        border: thick $warning;
        width: 60;
        height: 12;
    }

    #confirm-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    #confirm-prompt {
        color: $text;
        margin-bottom: 1;
    }

    #confirm-buttons {
        height: 3;
        align: right middle;
    }

    Button {
        margin-left: 1;
    }
    """

    def __init__(self, title: str, prompt_text: str) -> None:
        super().__init__()
        self.title_text = title
        self.prompt_text = prompt_text

    def compose(self) -> ComposeResult:
        with Container(id="confirm-dialog"):
            yield Label(self.title_text, id="confirm-title")
            yield Static(self.prompt_text, id="confirm-prompt")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel [Esc]", variant="error", id="cancel")
                yield Button("Confirm [Enter]", variant="primary", id="confirm")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class JulesTUIApp(App):
    """Main Textual application for Google Jules API session management."""
    TITLE = "Jules Vanager TUI"
    SUB_TITLE = "Google Jules API & Listener Management"
    
    BINDINGS = [
        Binding("r", "refresh_sessions", "Refresh", show=True),
        Binding("a", "archive_selected", "Archive", show=True),
        Binding("m", "cycle_filter", "Filter Mode", show=True),
        Binding("enter", "inspect_reply", "Reply / Inspect", show=True),
        Binding("s", "toggle_service", "Toggle Service", show=True),
        Binding("b", "toggle_autostart", "Toggle Autostart", show=True),
        Binding("w", "open_web_ui", "Web UI", show=True),
        Binding("p", "open_pr", "Open PR", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    Screen {
        background: #000000;
        color: #eab308;
    }

    #top-title-bar {
        dock: top;
        height: 1;
        background: #eab308;
        color: #000000;
        text-align: center;
        text-style: bold;
    }

    #status-bar {
        dock: top;
        height: 1;
        background: #18181b;
        color: #facc15;
        text-align: center;
    }

    #left-pane {
        width: 45%;
        border-right: solid #eab308;
        height: 100%;
        background: #0a0a0a;
    }

    #right-pane {
        width: 55%;
        height: 100%;
        padding: 1 2;
        background: #050505;
        color: #06b6d4;
    }

    ListView {
        height: 100%;
        background: #0a0a0a;
    }

    ListItem {
        padding: 0 1;
        height: auto;
        color: #eab308;
        background: #0a0a0a;
        border-bottom: dashed #334155;
    }

    .item-layout {
        height: auto;
        layout: horizontal;
    }

    ListItem:focus, ListItem.--highlight {
        background: #1f2937;
    }

    ListItem:focus .item-title, ListItem.--highlight .item-title {
        color: #facc15;
        text-style: bold;
    }

    .item-badge {
        width: auto;
        margin-right: 1;
    }

    .item-title {
        width: 1fr;
    }

    /* Increase specificity so focus/highlight doesn't override */
    ListItem .item-badge.state-success {
        color: #22c55e;
        text-style: bold;
    }

    ListItem .item-badge.state-error {
        color: #ef4444;
        text-style: bold;
    }

    ListItem .item-badge.state-active {
        color: #f59e0b;
        text-style: bold;
    }

    ListItem .item-badge.state-neutral {
        color: #71717a;
    }

    #detail-header {
        text-style: bold;
        color: #eab308;
        margin-bottom: 1;
    }

    #detail-content {
        height: 100%;
        color: #38bdf8;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.sessions: List[Dict[str, Any]] = load_cached_sessions()
        self.filter_mode: str = "ALL"  # ALL, ACTIVE, AWAITING, COMPLETED
        self.status_msg: str = "Ready"
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_idx = 0
        self.title_pulse = False

    def compose(self) -> ComposeResult:
        yield Static(" 󱚝 GOOGLE JULES API VANAGER & LISTENER TUI ", id="top-title-bar")
        yield Static("Initializing Jules TUI...", id="status-bar")
        with Horizontal():
            with Container(id="left-pane"):
                yield ListView(id="session-list")
            with ScrollableContainer(id="right-pane"):
                yield Label("Select a session from the list", id="detail-header")
                yield Markdown("No session selected.", id="detail-content")
        yield Footer()

    def on_mount(self) -> None:
        self.populate_session_list()
        self.fetch_data_worker()
        self.set_interval(0.1, self.animate_status_bar)

    def animate_status_bar(self) -> None:
        try:
            bar = self.query_one("#status-bar", Static)
            spinner = self.spinner_frames[self.spinner_idx % len(self.spinner_frames)]
            self.spinner_idx += 1
            bar.update(f" {spinner} Mode: [{self.filter_mode}] | {self.status_msg}")
        except Exception:
            pass

    def update_status(self, msg: str) -> None:
        self.status_msg = msg

    def populate_session_list(self) -> None:
        try:
            list_view = self.query_one("#session-list", ListView)
            list_view.clear()

            filtered = []
            for s in self.sessions:
                st = s.get("state", "").upper()
                if self.filter_mode == "ACTIVE" and st not in ("IN_PROGRESS", "RUNNING", "AWAITING_INPUT"):
                    continue
                if self.filter_mode == "AWAITING" and "AWAITING" not in st:
                    continue
                if self.filter_mode == "COMPLETED" and st not in ("COMPLETED", "SUCCEEDED", "RESOLVED", "MERGED"):
                    continue
                filtered.append(s)

            # Priority order: Awaiting input/feedback > Running/In Progress > Others
            def state_priority(s: Dict[str, Any]) -> int:
                st = (s.get("state") or "").upper()
                if "AWAITING" in st or "PAUSED" in st:
                    return 0
                if "IN_PROGRESS" in st or "RUNNING" in st:
                    return 1
                if st in ("COMPLETED", "SUCCEEDED", "RESOLVED", "MERGED"):
                    return 3
                return 2

            filtered.sort(key=state_priority)

            if not filtered:
                list_view.mount(ListItem(Label("No sessions found for current filter mode.", classes="state-neutral")))
                return

            for s in filtered:
                list_view.mount(SessionItem(s))
        except Exception:
            pass

    @work(exclusive=True, thread=True)
    def fetch_data_worker(self) -> None:
        """Background worker thread fetching sessions without UI blocking."""
        try:
            res = list_sessions(include_archived=False)
            raw_sessions = res.get("sessions", []) if isinstance(res, dict) else []
            new_sessions = [s for s in raw_sessions if s.get("state") not in ("ARCHIVED", "CLOSED")]
            
            unassigned = get_unassigned_jules_prs(new_sessions)
            new_sessions.extend(unassigned)
            
            if new_sessions:
                save_cached_sessions(new_sessions)
                self.sessions = new_sessions
                self.call_from_thread(self.populate_session_list)
                self.call_from_thread(self.update_status, f"Fetched {len(new_sessions)} sessions.")
        except Exception as e:
            self.call_from_thread(self.update_status, f"Fetch error: {e}")

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, SessionItem):
            s = event.item.session
            sid = event.item.sid
            title = s.get("title") or s.get("prompt") or f"Session {sid}"
            state = s.get("state", "UNKNOWN")
            
            header = self.query_one("#detail-header", Label)
            header.update(f"📌 {title}\nID: {sid} | State: {state}")

            content = self.query_one("#detail-content", Markdown)
            body_md = f"### Session Overview\n- **ID:** `{sid}`\n- **State:** `{state}`\n- **Prompt:** {s.get('prompt', 'N/A')}\n"
            content.update(body_md)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, SessionItem):
            self.action_inspect_reply()

    def action_refresh_sessions(self) -> None:
        self.update_status("Refreshing sessions...")
        self.fetch_data_worker()

    def action_cycle_filter(self) -> None:
        modes = ["ALL", "ACTIVE", "AWAITING", "COMPLETED"]
        idx = (modes.index(self.filter_mode) + 1) % len(modes)
        self.filter_mode = modes[idx]
        self.update_status(f"Filter mode set to {self.filter_mode}")
        self.populate_session_list()

    def action_inspect_reply(self) -> None:
        list_view = self.query_one("#session-list", ListView)
        if isinstance(list_view.highlighted_child, SessionItem):
            s = list_view.highlighted_child.session
            sid = list_view.highlighted_child.sid
            prompt = s.get("prompt") or s.get("title") or "Active Task"

            def handle_reply(reply_text: Optional[str]) -> None:
                if reply_text:
                    self.update_status(f"Sending reply to session {sid}...")
                    self.send_reply_worker(sid, reply_text)

            self.push_screen(ReplyModalScreen(sid, prompt), handle_reply)

    @work(exclusive=True, thread=True)
    def send_reply_worker(self, sid: str, reply_text: str) -> None:
        try:
            res = send_message(sid, reply_text)
            self.call_from_thread(self.update_status, f"Reply sent to {sid}.")
            self.fetch_data_worker()
        except Exception as e:
            self.call_from_thread(self.update_status, f"Error sending reply: {e}")

    def action_archive_selected(self) -> None:
        list_view = self.query_one("#session-list", ListView)
        if isinstance(list_view.highlighted_child, SessionItem):
            sid = list_view.highlighted_child.sid
            self.update_status(f"Archiving session {sid}...")
            self.archive_worker(sid)

    @work(exclusive=True, thread=True)
    def archive_worker(self, sid: str) -> None:
        try:
            archive_session(sid)
            self.call_from_thread(self.update_status, f"Archived session {sid}.")
            self.fetch_data_worker()
        except Exception as e:
            self.call_from_thread(self.update_status, f"Archive error: {e}")

    def action_toggle_service(self) -> None:
        def handle_confirm(confirmed: bool) -> None:
            if confirmed:
                msg = toggle_systemd_service()
                self.update_status(msg)

        self.push_screen(ConfirmModalScreen("⚠️ Toggle Listener Service", "Are you sure you want to stop/start the jules-listener systemd service?"), handle_confirm)

    def action_toggle_autostart(self) -> None:
        msg = toggle_systemd_autostart()
        self.update_status(msg)

    def action_open_web_ui(self) -> None:
        list_view = self.query_one("#session-list", ListView)
        url = "https://jules.google.com"
        if isinstance(list_view.highlighted_child, SessionItem):
            sid = list_view.highlighted_child.sid
            url = f"https://jules.google.com/task/{sid}"
        webbrowser.open(url)
        self.update_status(f"Opened web UI: {url}")

    def action_open_pr(self) -> None:
        list_view = self.query_one("#session-list", ListView)
        if isinstance(list_view.highlighted_child, SessionItem):
            s = list_view.highlighted_child.session
            pr_st = check_session_pr_status(s)
            url = pr_st.get("url")
            if url:
                webbrowser.open(url)
                self.update_status(f"Opened PR: {url}")
            else:
                self.update_status("No PR found for selected session.")


def main() -> None:
    # Auto-kill prior jules_tui instances and their Kitty parent windows on startup
    current_pid = os.getpid()
    try:
        out = subprocess.check_output(["pgrep", "-f", "jules_tui.py"], text=True)
        for line in out.strip().splitlines():
            try:
                pid = int(line.strip())
                if pid != current_pid:
                    try:
                        ppid_out = subprocess.check_output(["ps", "-o", "ppid=", "-p", str(pid)], text=True).strip()
                        ppid = int(ppid_out)
                        if ppid > 1 and ppid != current_pid:
                            os.kill(ppid, signal.SIGKILL)
                    except Exception:
                        pass
                    os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
    except Exception:
        pass

    app = JulesTUIApp()
    app.run()


if __name__ == "__main__":
    main()
