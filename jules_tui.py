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
import signal
from typing import List, Dict, Any, Optional, Tuple

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, Static, ListView, ListItem, Label, Input, Button, Markdown, TextArea
from textual.worker import Worker, WorkerState
from textual.reactive import reactive
from textual import work, events
import operator
from functools import cached_property
from textual.visual import Style
from textual.color import Color
from textual.renderables.blank import Blank
from rich.style import Style as RichStyle
import rich.color
import textual.filter
from textual.theme import Theme

# Compatibility patch: Allow rich to parse textual Color instances (e.g. for TextArea fallback styling)
_orig_rich_color_parse = rich.color.Color.parse

def _patched_rich_color_parse(color: Any) -> rich.color.Color:
    if isinstance(color, Color):
        return color.rich_color
    return _orig_rich_color_parse(color)

rich.color.Color.parse = _patched_rich_color_parse

# Compatibility patch: Prevent monochrome filter crash when Segment style is None
_orig_monochrome_style = textual.filter.monochrome_style

def _patched_monochrome_style(style: Any) -> RichStyle:
    if style is None:
        return RichStyle()
    return _orig_monochrome_style(style)

textual.filter.monochrome_style = _patched_monochrome_style

# Force Textual Blank renderable to be transparent when color is transparent
def _patched_blank_init(self, color: Color | str = "transparent") -> None:
    c = Color.parse(color) if isinstance(color, str) else color
    if c.a == 0:
        self._rich_style = RichStyle()
    else:
        self._rich_style = RichStyle.from_color(bgcolor=c.rich_color)

Blank.__init__ = _patched_blank_init

# Force Textual Visual Style conversion to omit background color when alpha is 0
_get_simple_attrs = operator.attrgetter(
    "background", "foreground", "bold", "dim", "italic",
    "underline", "underline2", "reverse", "strike", "blink",
    "link", "_meta"
)

def _patched_style_rich_style(self):
    (
        background, foreground, bold, dim, italic,
        underline, underline2, reverse, strike, blink,
        link, _meta
    ) = _get_simple_attrs(self)

    color = None if foreground is None else background + foreground
    bg_rich = None if (background is None or background.a == 0) else background.rich_color

    return RichStyle(
        color=None if color is None else color.rich_color,
        bgcolor=bg_rich,
        bold=bold,
        dim=dim,
        italic=italic,
        underline=underline,
        underline2=underline2,
        reverse=reverse,
        strike=strike,
        blink=blink,
        link=link,
        meta=None if _meta is None else self.meta,
    )

_cp = cached_property(_patched_style_rich_style)
_cp.__set_name__(Style, "rich_style")
Style.rich_style = _cp

def _patched_style_rich_style_with_offset(self, x: int, y: int) -> RichStyle:
    (
        background, foreground, bold, dim, italic,
        underline, underline2, reverse, strike, blink,
        link, _meta
    ) = _get_simple_attrs(self)

    color = None if foreground is None else background + foreground
    bg_rich = None if (background is None or background.a == 0) else background.rich_color

    return RichStyle(
        color=None if color is None else color.rich_color,
        bgcolor=bg_rich,
        bold=bold,
        dim=dim,
        italic=italic,
        underline=underline,
        underline2=underline2,
        reverse=reverse,
        strike=strike,
        blink=blink,
        link=link,
        meta={**self.meta, "offset": (x, y)},
    )

Style.rich_style_with_offset = _patched_style_rich_style_with_offset

TRANSPARENT_THEME = Theme(
    name="transparent-theme",
    primary="#eab308",
    secondary="#eab308",
    warning="#f59e0b",
    error="#ef4444",
    success="#22c55e",
    accent="#eab308",
    foreground="#eab308",
    background=Color(0, 0, 0, 0),
    surface=Color(0, 0, 0, 0),
    panel=Color(0, 0, 0, 0),
    boost=Color(0, 0, 0, 0),
    dark=True,
    variables={
        "block-cursor-blurred-background": "transparent",
        "block-hover-background": "transparent",
        "block-cursor-background": "#eab308",
        "footer-background": "transparent",
        "markdown-h1-background": "transparent",
        "markdown-h2-background": "transparent",
        "markdown-h3-background": "transparent",
        "markdown-h4-background": "transparent",
        "markdown-h5-background": "transparent",
        "markdown-h6-background": "transparent",
    }
)

# Import API manager functions
from jules_manager import list_sessions, get_session_activities, send_message, archive_session, unarchive_session, _make_request

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

def is_listener_service_active() -> bool:
    try:
        check = subprocess.run(["systemctl", "--user", "is-active", "jules-listener.service"], capture_output=True, text=True)
        return check.stdout.strip() == "active"
    except Exception:
        return False

_SESSION_ACTIVITIES_CACHE: Dict[str, Dict[str, Any]] = {}
_SESSION_ACTIVITIES_CACHE_TIME: Dict[str, float] = {}

def parse_session_activities(activities: List[Dict[str, Any]]) -> Dict[str, Any]:
    question = None
    failure_reason = None
    for a in activities:
        if "agentMessaged" in a:
            msg = a["agentMessaged"].get("agentMessage", "")
            if msg:
                question = msg
        if "sessionFailed" in a:
            reason = a["sessionFailed"].get("reason", "")
            if reason:
                failure_reason = reason
    return {
        "question": question,
        "failure_reason": failure_reason,
        "total_activities": len(activities),
    }

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
        yield Static("", id="item-static")

    def on_mount(self) -> None:
        self.update_rendering()

    def watch_has_focus(self, value: bool) -> None:
        self.update_rendering()

    def update_rendering(self) -> None:
        state = self.session.get("state", "UNKNOWN")
        title = self.session.get("title") or self.session.get("prompt") or f"Session {self.sid}"
        if len(title) > 50:
            title = title[:47] + "..."

        is_focused = False
        try:
            list_view = self.app.query_one("#session-list", ListView)
            if list_view.highlighted_child is self:
                is_focused = True
        except Exception:
            pass

        archive_time = self.session.get("archived_at") or self.session.get("updateTime") or self.session.get("createTime") or ""
        if archive_time and "T" in archive_time:
            archive_time = archive_time.replace("T", " ").split(".")[0][:16]

        is_answering = False
        spinner_char = "⠋"
        if getattr(self.app, "answering_sessions", None) and self.sid in self.app.answering_sessions:
            is_answering = True
            if hasattr(self.app, "spinner_frames") and hasattr(self.app, "spinner_idx"):
                spinner_char = self.app.spinner_frames[self.app.spinner_idx % len(self.app.spinner_frames)]
        elif self.session.get("is_answering"):
            is_answering = True

        from rich.text import Text
        txt = Text()

        display_badge = f"[{spinner_char} ANSWERING]" if is_answering else f"[{state}]"

        if is_focused:
            time_suffix = f" ({archive_time})" if archive_time and (state in ("ARCHIVED", "CLOSED") or getattr(self.app, "show_archived", False)) else ""
            txt.append(f"{display_badge} {title}{time_suffix}", style="bold #000000 on #eab308")
        else:
            if is_answering:
                badge_style = "bold #38bdf8"
            elif state in ("COMPLETED", "SUCCEEDED", "RESOLVED", "MERGED"):
                badge_style = "bold #22c55e"
            elif "FAIL" in state or "CONFLICT" in state or "REJECTED" in state:
                badge_style = "bold #ef4444"
            elif "AWAITING" in state or "IN_PROGRESS" in state or "RUNNING" in state:
                badge_style = "bold #f59e0b"
            else:
                badge_style = "#71717a"

            txt.append(display_badge, style=badge_style)
            txt.append(f" {title}", style="#eab308")
            if archive_time and (state in ("ARCHIVED", "CLOSED") or getattr(self.app, "show_archived", False)):
                txt.append(f"  {archive_time}", style="#71717a")

        try:
            self.query_one("#item-static", Static).update(txt)
        except Exception:
            pass


class ReplyModalScreen(ModalScreen[Optional[str]]):
    """Modal screen for sending prompt responses to an active session."""
    BINDINGS = [
        Binding("escape", "dismiss_modal", "Cancel", show=True),
        Binding("ctrl+s", "submit_reply", "Submit", show=True),
        Binding("ctrl+j", "submit_reply", "Submit", show=False),
        Binding("ctrl+enter", "submit_reply", "Submit", show=False),
        Binding("pageup", "scroll_up", "Scroll Up", show=False),
        Binding("pagedown", "scroll_down", "Scroll Down", show=False),
        Binding("shift+up", "scroll_up", "Scroll Up", show=False),
        Binding("shift+down", "scroll_down", "Scroll Down", show=False),
    ]

    DEFAULT_CSS = """
    $surface: transparent;
    $surface-lighten-1: transparent;
    $surface-lighten-2: transparent;
    $surface-lighten-3: transparent;
    $surface-darken-1: transparent;
    $surface-darken-2: transparent;
    $surface-darken-3: transparent;
    $panel: transparent;
    $panel-lighten-1: transparent;
    $panel-darken-1: transparent;
    $background: transparent;
    $boost: transparent;
    $footer-background: transparent;
    $footer-description-background: transparent;
    $footer-key-background: transparent;

    * {
        background: transparent !important;
    }

    ReplyModalScreen {
        align: center middle;
        background: transparent !important;
    }

    #dialog {
        padding: 1 2;
        background: transparent !important;
        border: thick $primary;
        width: 85;
        max-width: 90%;
        height: auto;
        max-height: 85%;
    }

    #dialog-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
        background: transparent !important;
    }

    #dialog-scroll {
        height: auto;
        max-height: 14;
        min-height: 3;
        overflow-y: auto;
        margin-bottom: 1;
        border: solid #3f3f46;
        padding: 0 1;
        background: transparent !important;
    }

    #dialog-prompt {
        color: #facc15;
        background: transparent !important;
        width: 100%;
    }

    #reply-input {
        margin: 1 0;
        height: 7;
        min-height: 4;
        max-height: 12;
        background: transparent !important;
        border: tall #eab308;
    }

    TextArea, TextArea:focus, TextArea .text-area--cursor-line, TextArea .text-area--cursor-gutter {
        background: transparent !important;
        color: #facc15;
    }

    TextArea .text-area--placeholder {
        color: #71717a;
    }

    #buttons {
        height: 3;
        align: right middle;
        background: transparent !important;
    }

    Button, Button:focus, Button:hover {
        margin-left: 1;
        background: transparent !important;
    }
    """

    def __init__(self, session_id: str, prompt_text: str, question: Optional[str] = None) -> None:
        super().__init__()
        self.session_id = session_id
        self.prompt_text = prompt_text
        self.question = question

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            if self.question:
                yield Label(f"❓ Jules' Question [{self.session_id}]", id="dialog-title")
                with VerticalScroll(id="dialog-scroll"):
                    yield Static(f"Feedback Request:\n\n{self.question}", id="dialog-prompt")
            else:
                yield Label(f"🤖 Reply to Session [{self.session_id}]", id="dialog-title")
                with VerticalScroll(id="dialog-scroll"):
                    yield Static(f"Prompt:\n\n{self.prompt_text}", id="dialog-prompt")
            yield TextArea(
                id="reply-input",
                show_line_numbers=False,
                soft_wrap=True,
                tab_behavior="focus",
                placeholder="Type multiline message reply...\n[Ctrl+Enter / Ctrl+S] to submit, [Esc] to cancel"
            )
            with Horizontal(id="buttons"):
                yield Button("Cancel [Esc]", variant="error", id="cancel")
                yield Button("Submit [Ctrl+Enter]", variant="primary", id="submit")

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def action_scroll_up(self) -> None:
        try:
            self.query_one("#dialog-scroll", VerticalScroll).scroll_relative(y=-3)
        except Exception:
            pass

    def action_scroll_down(self) -> None:
        try:
            self.query_one("#dialog-scroll", VerticalScroll).scroll_relative(y=3)
        except Exception:
            pass

    def action_submit_reply(self) -> None:
        try:
            val = self.query_one(TextArea).text.strip()
            self.dismiss(val if val else None)
        except Exception:
            self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key in ("ctrl+enter", "ctrl+j", "ctrl+s"):
            event.stop()
            event.prevent_default()
            self.action_submit_reply()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit_reply()
        else:
            self.dismiss(None)

class ConfirmModalScreen(ModalScreen[bool]):
    """Modal screen for action confirmation prompts."""
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    DEFAULT_CSS = """
    $surface: transparent;
    $surface-lighten-1: transparent;
    $surface-lighten-2: transparent;
    $surface-lighten-3: transparent;
    $surface-darken-1: transparent;
    $surface-darken-2: transparent;
    $surface-darken-3: transparent;
    $panel: transparent;
    $panel-lighten-1: transparent;
    $panel-darken-1: transparent;
    $background: transparent;
    $boost: transparent;
    $footer-background: transparent;
    $footer-description-background: transparent;
    $footer-key-background: transparent;

    * {
        background: transparent !important;
    }

    ConfirmModalScreen {
        align: center middle;
        background: transparent !important;
    }

    #confirm-dialog {
        padding: 1 2;
        background: transparent !important;
        border: thick $warning;
        width: 60;
        height: 12;
    }

    #confirm-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
        background: transparent !important;
    }

    #confirm-prompt {
        color: $text;
        margin-bottom: 1;
        background: transparent !important;
    }

    #confirm-buttons {
        height: 3;
        align: right middle;
        background: transparent !important;
    }

    Button, Button:focus, Button:hover {
        margin-left: 1;
        background: transparent !important;
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
        Binding("v", "toggle_archived", "Archived Panel", show=True),
        Binding("m", "cycle_filter", "Filter Mode", show=True),
        Binding("enter", "inspect_reply", "Reply / Inspect", show=True),
        Binding("s", "toggle_service", "Toggle Service", show=True),
        Binding("b", "toggle_autostart", "Toggle Autostart", show=True),
        Binding("w", "open_web_ui", "Web UI", show=True),
        Binding("p", "open_pr", "Open PR", show=True),
        Binding("pageup", "scroll_detail_up", "Scroll Detail Up", show=False),
        Binding("pagedown", "scroll_detail_down", "Scroll Detail Down", show=False),
        Binding("shift+up", "scroll_detail_up", "Scroll Detail Up", show=False),
        Binding("shift+down", "scroll_detail_down", "Scroll Detail Down", show=False),
        Binding("q", "quit", "Quit", show=True),
    ]

    def check_action_archive_selected(self) -> Tuple[bool, str]:
        """Dynamically supply action state and label to Textual Footer."""
        label = "Unarchive" if self.show_archived else "Archive"
        return True, label

    CSS = """
    $surface: transparent;
    $surface-lighten-1: transparent;
    $surface-lighten-2: transparent;
    $surface-lighten-3: transparent;
    $surface-darken-1: transparent;
    $surface-darken-2: transparent;
    $surface-darken-3: transparent;
    $panel: transparent;
    $panel-lighten-1: transparent;
    $panel-darken-1: transparent;
    $background: transparent;
    $boost: transparent;
    $footer-background: transparent;
    $footer-description-background: transparent;
    $footer-key-background: transparent;

    * {
        background: transparent !important;
    }

    Screen, ModalScreen, App {
        background: transparent !important;
        color: #eab308;
    }

    #header-container {
        dock: top;
        height: auto;
        width: 100%;
        background: transparent !important;
    }

    #top-header {
        height: 1;
        width: 100%;
        background: #eab308 !important;
        color: #000000 !important;
        text-align: center;
        text-style: bold;
    }

    Footer {
        dock: bottom;
        height: 1;
        background: transparent !important;
        color: #eab308;
    }

    FooterKey, FooterLabel, FooterKey .footer-key--key, FooterKey .footer-key--description, Footer > .footer--highlight {
        background: transparent !important;
    }

    #status-bar {
        height: auto;
        min-height: 1;
        width: 100%;
        background: #000000 !important;
        background-tint: transparent !important;
        color: #facc15;
        text-style: bold;
        text-align: center;
        border-bottom: none;
    }

    #left-pane {
        width: 45%;
        border-right: solid #eab308;
        height: 100%;
        background: transparent !important;
    }

    #right-pane {
        width: 55%;
        height: 100%;
        padding: 1 2;
        background: transparent !important;
        color: #06b6d4;
    }

    Container, ScrollableContainer, Vertical, Horizontal, ListView, ListItem, Static, Label, Input, Button, Header, Footer, FooterKey, FooterLabel, Markdown, MarkdownBlock, MarkdownHeader, MarkdownParagraph, MarkdownUnorderedList, MarkdownOrderedList, MarkdownListItem, MarkdownFence, MarkdownCodeBlock, MarkdownTable, MarkdownTableCell, MarkdownTableTitle, ScrollBar, ScrollBarCorner, ScrollbarHandle, ScrollBarHandle, ScrollBarGrip, TextArea {
        background: transparent !important;
    }

    TextArea, TextArea:focus, TextArea .text-area--cursor-line, TextArea .text-area--cursor-gutter {
        background: transparent !important;
    }

    Input, Input:focus, Input.--cursor, Input > .input--placeholder {
        background: transparent !important;
        border: tall #eab308;
    }

    Button, Button:focus, Button:hover {
        background: transparent !important;
    }

    ListView, ListView:focus {
        background: transparent !important;
        background-tint: transparent !important;
    }

    ListView > ListItem, ListView > ListItem:enabled, ListView > ListItem:hover, ListView > ListItem.-hovered {
        background: transparent !important;
        background-tint: transparent !important;
    }

    ListView > ListItem.-highlight, ListItem.-highlight {
        background: transparent !important;
        background-tint: transparent !important;
    }

    ListItem, ListItem:enabled, ListItem:hover {
        padding: 0 1;
        height: auto;
        color: #eab308;
        background: transparent !important;
        background-tint: transparent !important;
        border-bottom: none;
    }

    #item-static {
        width: 100%;
        background: transparent !important;
    }

    ListItem:focus, ListItem.-highlight, ListView > ListItem:focus, ListView > ListItem.-highlight {
        background: #eab308 !important;
        color: #000000 !important;
    }

    ListItem:focus Static, ListItem.-highlight Static, ListView > ListItem:focus Static, ListView > ListItem.-highlight Static {
        background: #eab308 !important;
        color: #000000 !important;
    }

    Markdown, MarkdownBlock, MarkdownHeader, MarkdownParagraph, MarkdownUnorderedList, MarkdownOrderedList, MarkdownListItem, MarkdownFence, MarkdownCodeBlock, MarkdownTable, MarkdownTableCell, MarkdownTableTitle, MarkdownQuote, MarkdownBullet, MarkdownEmphasis, MarkdownStrong, MarkdownH1, MarkdownH2, MarkdownH3, MarkdownH4, MarkdownH5, MarkdownH6 {
        background: transparent !important;
        background-tint: transparent !important;
    }

    MarkdownBlock > .code_inline {
        background: transparent !important;
        color: #facc15 !important;
    }

    ScrollBar, ScrollBarCorner, ScrollBarHandle, ScrollBarGrip, ScrollBar.--vertical, ScrollBar.--horizontal {
        background: transparent !important;
    }

    .state-success {
        color: #22c55e;
        text-style: bold;
    }

    .state-error {
        color: #ef4444;
        text-style: bold;
    }

    .state-active {
        color: #f59e0b;
        text-style: bold;
    }

    .state-neutral {
        color: #71717a;
    }

    #detail-header {
        text-style: bold;
        color: #eab308;
        margin-bottom: 1;
        background: transparent !important;
    }

    #detail-content {
        height: 100%;
        color: #38bdf8;
        background: transparent !important;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.sessions: List[Dict[str, Any]] = load_cached_sessions()
        self.filter_mode: str = "ALL"  # ALL, ACTIVE, AWAITING, COMPLETED, ARCHIVED
        self.show_archived: bool = False
        self.status_msg: str = "Ready"
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_idx = 0
        self.title_pulse = False
        self.answering_sessions: Dict[str, float] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="header-container"):
            yield Static(" 󱚝 GOOGLE JULES API VANAGER & LISTENER TUI ", id="top-header")
            yield Static("Initializing Jules TUI...", id="status-bar")
        with Horizontal():
            with Container(id="left-pane"):
                yield ListView(id="session-list")
            with ScrollableContainer(id="right-pane"):
                yield Label("Select a session from the list", id="detail-header")
                yield Markdown("No session selected.", id="detail-content")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(TRANSPARENT_THEME)
        self.theme = "transparent-theme"
        self.populate_session_list()
        self.fetch_data_worker()
        self.set_interval(0.1, self.animate_status_bar)

    def animate_status_bar(self) -> None:
        try:
            self.spinner_idx = (self.spinner_idx + 1) % len(self.spinner_frames)
            spinner = self.spinner_frames[self.spinner_idx]
            bar = self.query_one("#status-bar", Static)
            is_active_op = any(kw in self.status_msg.lower() for kw in ("fetching", "refreshing", "sending", "archiving", "syncing"))
            service_active = is_listener_service_active()
            
            if is_active_op:
                listener_str = f"⚡ Listener: RUNNING {spinner}"
            elif service_active:
                listener_str = "● Listener: ACTIVE (systemd)"
            else:
                listener_str = "○ Listener: STOPPED"

            if self.show_archived:
                panel_str = "📂 VIEW: ARCHIVED SESSIONS PANEL"
            else:
                panel_str = f"📋 VIEW: ACTIVE SESSIONS ({self.filter_mode})"

            bar.update(f" {panel_str} | {listener_str} | {self.status_msg}")

            if getattr(self, "answering_sessions", None):
                now = time.time()
                expired = [sid for sid, ts in self.answering_sessions.items() if (now - ts) > 180]
                for sid in expired:
                    del self.answering_sessions[sid]

                list_view = self.query_one("#session-list", ListView)
                for item in list_view.children:
                    if isinstance(item, SessionItem) and item.sid in self.answering_sessions:
                        item.update_rendering()

                if list_view.highlighted_child and getattr(list_view.highlighted_child, "sid", None) in self.answering_sessions:
                    cur_item = list_view.highlighted_child
                    sid = cur_item.sid
                    s = cur_item.session
                    title = s.get("title") or s.get("prompt") or f"Session {sid}"
                    self.query_one("#detail-header", Label).update(f"📌 {title}\nID: {sid} | State: ANSWERING {spinner}")
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
                sid = s.get("id") or s.get("name", "").split("/")[-1]
                is_answering = sid in getattr(self, "answering_sessions", {})
                st = s.get("state", "").upper()
                is_archived = st in ("ARCHIVED", "CLOSED") or s.get("archived", False)
                
                if self.show_archived:
                    if is_archived:
                        filtered.append(s)
                else:
                    if is_archived:
                        continue
                    if self.filter_mode == "ACTIVE" and not (
                        "IN_PROGRESS" in st or "RUNNING" in st or "AWAITING" in st or "PAUSED" in st or is_answering
                    ):
                        continue
                    if self.filter_mode == "AWAITING" and not ("AWAITING" in st or is_answering):
                        continue
                    if self.filter_mode == "FAILED" and "FAIL" not in st and "ERROR" not in st:
                        continue
                    if self.filter_mode == "COMPLETED" and st not in ("COMPLETED", "SUCCEEDED", "RESOLVED", "MERGED"):
                        continue
                    filtered.append(s)

            # Priority order: Answering > Awaiting input/feedback > Running/In Progress > Failed/Errors > Others > Completed
            def state_priority(s: Dict[str, Any]) -> int:
                sid = s.get("id") or s.get("name", "").split("/")[-1]
                if sid in getattr(self, "answering_sessions", {}):
                    return -1
                st = (s.get("state") or "").upper()
                if "AWAITING" in st or "PAUSED" in st:
                    return 0
                if "IN_PROGRESS" in st or "RUNNING" in st:
                    return 1
                if "FAIL" in st or "ERROR" in st or "CONFLICT" in st:
                    return 2
                if st in ("COMPLETED", "SUCCEEDED", "RESOLVED", "MERGED"):
                    return 4
                return 3

            filtered.sort(key=state_priority)

            if not filtered:
                msg = "No archived sessions found." if self.show_archived else f"No sessions found for filter [{self.filter_mode}]."
                list_view.mount(ListItem(Label(msg, classes="state-neutral")))
                return

            for s in filtered:
                list_view.mount(SessionItem(s))
        except Exception:
            pass

    @work(exclusive=True, thread=True)
    def fetch_data_worker(self) -> None:
        """Background worker thread fetching sessions without UI blocking."""
        try:
            active_res = list_sessions(include_archived=False)
            active_sessions = active_res.get("sessions", []) if isinstance(active_res, dict) else []
            for s in active_sessions:
                s["archived"] = False

            archived_res = list_sessions(include_archived=True)
            archived_sessions = archived_res.get("sessions", []) if isinstance(archived_res, dict) else []
            for s in archived_sessions:
                s["archived"] = True

            all_sessions = []
            seen_ids = set()
            for s in active_sessions:
                sid = s.get("id") or s.get("name", "").split("/")[-1]
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    all_sessions.append(s)
                if sid in getattr(self, "answering_sessions", {}):
                    st = (s.get("state") or "").upper()
                    if "IN_PROGRESS" in st or "RUNNING" in st or "COMPLETED" in st or "FAIL" in st:
                        self.answering_sessions.pop(sid, None)

            for s in archived_sessions:
                sid = s.get("id") or s.get("name", "").split("/")[-1]
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    all_sessions.append(s)

            unassigned = get_unassigned_jules_prs(all_sessions)
            all_sessions.extend(unassigned)

            if all_sessions:
                save_cached_sessions(all_sessions)
                self.sessions = all_sessions
                self.call_from_thread(self.populate_session_list)
                self.call_from_thread(
                    self.update_status,
                    f"Fetched {len(active_sessions)} active, {len(archived_sessions)} archived sessions."
                )
        except Exception as e:
            self.call_from_thread(self.update_status, f"Fetch error: {e}")

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        try:
            list_view = self.query_one("#session-list", ListView)
            for item in list_view.children:
                if isinstance(item, SessionItem):
                    item.update_rendering()
        except Exception:
            pass

        if isinstance(event.item, SessionItem):
            s = event.item.session
            sid = event.item.sid
            title = s.get("title") or s.get("prompt") or f"Session {sid}"
            state = s.get("state", "UNKNOWN")
            
            archive_time = s.get("archived_at") or s.get("updateTime") or s.get("createTime") or "N/A"
            if archive_time != "N/A" and "T" in archive_time:
                archive_time = archive_time.replace("T", " ").split(".")[0][:19]

            is_answering = sid in getattr(self, "answering_sessions", {})
            header = self.query_one("#detail-header", Label)
            if is_answering:
                spinner_char = self.spinner_frames[self.spinner_idx % len(self.spinner_frames)]
                header.update(f"📌 {title}\nID: {sid} | State: ANSWERING {spinner_char}")
            else:
                header.update(f"📌 {title}\nID: {sid} | State: {state}")

            self.render_session_details(sid, s, archive_time)
            self.fetch_session_activities_worker(sid, s, archive_time)

    def render_session_details(self, sid: str, s: Dict[str, Any], archive_time: str) -> None:
        title = s.get("title") or s.get("prompt") or f"Session {sid}"
        state = s.get("state", "UNKNOWN")
        init_prompt = s.get("prompt", "N/A")

        is_answering = sid in getattr(self, "answering_sessions", {})
        display_state = "ANSWERING" if is_answering else state

        act_info = _SESSION_ACTIVITIES_CACHE.get(sid, {})
        question = act_info.get("question")
        failure_reason = act_info.get("failure_reason")
        act_count = act_info.get("total_activities")

        body_md = f"### Session Overview\n- **ID:** `{sid}`\n- **State:** `{display_state}`\n- **Updated:** `{archive_time}`\n"

        if is_answering:
            spinner = self.spinner_frames[self.spinner_idx % len(self.spinner_frames)]
            body_md += f"\n> ⏳ **Reply submitted to Jules! Awaiting response...** {spinner}\n"

        if question:
            body_md += f"\n### ❓ Jules' Feedback Request / Question\n> {question}\n\n👉 **Press `Enter` to reply directly to Jules**\n"

        if failure_reason:
            body_md += f"\n### ❌ Failure Reason\n```\n{failure_reason}\n```\n"

        body_md += f"\n### 📋 Initial Prompt\n{init_prompt}\n"

        if act_count is not None:
            body_md += f"\n- **Total Activities:** {act_count}\n"

        pr_st = check_session_pr_status(s)
        if pr_st.get("has_pr"):
            body_md += f"\n### 🐙 GitHub PR #{pr_st.get('pr_number')}\n- **URL:** {pr_st.get('url')}\n- **Mergeable:** {pr_st.get('mergeable')}\n"

        try:
            content = self.query_one("#detail-content", Markdown)
            content.update(body_md)
        except Exception:
            pass

    @work(thread=True)
    def fetch_session_activities_worker(self, sid: str, s: Dict[str, Any], archive_time: str) -> None:
        now = time.time()
        if sid in _SESSION_ACTIVITIES_CACHE and (now - _SESSION_ACTIVITIES_CACHE_TIME.get(sid, 0)) < 45:
            return
        try:
            act_res = get_session_activities(sid)
            activities = act_res.get("activities", []) if isinstance(act_res, dict) else []
            parsed = parse_session_activities(activities)
            _SESSION_ACTIVITIES_CACHE[sid] = parsed
            _SESSION_ACTIVITIES_CACHE_TIME[sid] = now

            list_view = self.query_one("#session-list", ListView)
            if list_view.highlighted_child and getattr(list_view.highlighted_child, "sid", None) == sid:
                self.call_from_thread(self.render_session_details, sid, s, archive_time)
        except Exception:
            pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, SessionItem):
            self.action_inspect_reply()

    def action_refresh_sessions(self) -> None:
        self.update_status("Refreshing sessions...")
        self.fetch_data_worker()

    def action_scroll_detail_up(self) -> None:
        try:
            self.query_one("#right-pane", ScrollableContainer).scroll_relative(y=-4)
        except Exception:
            pass

    def action_scroll_detail_down(self) -> None:
        try:
            self.query_one("#right-pane", ScrollableContainer).scroll_relative(y=4)
        except Exception:
            pass

    def check_action_archive_selected(self) -> Tuple[bool, str]:
        """Dynamically supply action state and label to Textual Footer."""
        label = "Unarchive" if self.show_archived else "Archive"
        return True, label

    def update_footer_bindings(self) -> None:
        try:
            target_desc = "Unarchive" if self.show_archived else "Archive"
            
            # Rebuild frozen Binding objects in _bindings.key_to_bindings for app and active screen
            for container in (self, self.screen):
                if hasattr(container, "_bindings") and hasattr(container._bindings, "key_to_bindings"):
                    for key, binding_list in list(container._bindings.key_to_bindings.items()):
                        new_list = []
                        for b in binding_list:
                            if getattr(b, "action", "") == "archive_selected" or getattr(b, "key", "") == "a":
                                new_list.append(Binding(b.key, b.action, target_desc, show=b.show, key_display=b.key_display))
                            else:
                                new_list.append(b)
                        container._bindings.key_to_bindings[key] = new_list

            self.screen.bindings_updated_signal.publish(self.screen)
        except Exception:
            pass

    def action_cycle_filter(self) -> None:
        if self.show_archived:
            self.show_archived = False
            self.update_footer_bindings()
        modes = ["ALL", "ACTIVE", "AWAITING", "FAILED", "COMPLETED"]
        idx = (modes.index(self.filter_mode) + 1) % len(modes)
        self.filter_mode = modes[idx]
        self.update_status(f"Filter mode set to {self.filter_mode}")
        self.populate_session_list()

    def action_toggle_archived(self) -> None:
        self.show_archived = not self.show_archived
        self.update_footer_bindings()
        view_str = "Archived Sessions" if self.show_archived else f"Active Sessions ({self.filter_mode})"
        self.update_status(f"Switched view to {view_str}")
        self.populate_session_list()

    def action_inspect_reply(self) -> None:
        list_view = self.query_one("#session-list", ListView)
        if isinstance(list_view.highlighted_child, SessionItem):
            s = list_view.highlighted_child.session
            sid = list_view.highlighted_child.sid
            prompt = s.get("prompt") or s.get("title") or "Active Task"
            act_info = _SESSION_ACTIVITIES_CACHE.get(sid, {})
            question = act_info.get("question")
            if not question:
                try:
                    act_res = get_session_activities(sid)
                    activities = act_res.get("activities", []) if isinstance(act_res, dict) else []
                    parsed = parse_session_activities(activities)
                    _SESSION_ACTIVITIES_CACHE[sid] = parsed
                    question = parsed.get("question")
                except Exception:
                    pass

            def handle_reply(reply_text: Optional[str]) -> None:
                if reply_text:
                    self.update_status(f"Sending reply to session {sid}...")
                    self.mark_session_answering(sid)
                    self.send_reply_worker(sid, reply_text)

            self.push_screen(ReplyModalScreen(sid, prompt, question=question), handle_reply)

    def mark_session_answering(self, sid: str) -> None:
        if not hasattr(self, "answering_sessions"):
            self.answering_sessions = {}
        self.answering_sessions[sid] = time.time()
        for s in self.sessions:
            s_id = s.get("id") or s.get("name", "").split("/")[-1]
            if s_id == sid:
                s["is_answering"] = True
                break
        try:
            list_view = self.query_one("#session-list", ListView)
            for item in list_view.children:
                if isinstance(item, SessionItem) and item.sid == sid:
                    item.update_rendering()
            if list_view.highlighted_child and getattr(list_view.highlighted_child, "sid", None) == sid:
                cur_item = list_view.highlighted_child
                s = cur_item.session
                archive_time = s.get("archived_at") or s.get("updateTime") or s.get("createTime") or "N/A"
                if "T" in archive_time:
                    archive_time = archive_time.replace("T", " ").split(".")[0]
                spinner = self.spinner_frames[self.spinner_idx % len(self.spinner_frames)]
                title = s.get("title") or s.get("prompt") or f"Session {sid}"
                self.query_one("#detail-header", Label).update(f"📌 {title}\nID: {sid} | State: ANSWERING {spinner}")
                self.render_session_details(sid, s, archive_time)
        except Exception:
            pass

    def clear_session_answering(self, sid: str) -> None:
        if hasattr(self, "answering_sessions") and sid in self.answering_sessions:
            del self.answering_sessions[sid]
        for s in self.sessions:
            s_id = s.get("id") or s.get("name", "").split("/")[-1]
            if s_id == sid:
                s.pop("is_answering", None)
                break
        try:
            list_view = self.query_one("#session-list", ListView)
            for item in list_view.children:
                if isinstance(item, SessionItem) and item.sid == sid:
                    item.update_rendering()
            if list_view.highlighted_child and getattr(list_view.highlighted_child, "sid", None) == sid:
                cur_item = list_view.highlighted_child
                s = cur_item.session
                archive_time = s.get("archived_at") or s.get("updateTime") or s.get("createTime") or "N/A"
                if "T" in archive_time:
                    archive_time = archive_time.replace("T", " ").split(".")[0]
                state = s.get("state", "UNKNOWN")
                title = s.get("title") or s.get("prompt") or f"Session {sid}"
                self.query_one("#detail-header", Label).update(f"📌 {title}\nID: {sid} | State: {state}")
                self.render_session_details(sid, s, archive_time)
        except Exception:
            pass

    @work(exclusive=True, thread=True)
    def send_reply_worker(self, sid: str, reply_text: str) -> None:
        try:
            res = send_message(sid, reply_text)
            self.call_from_thread(self.update_status, f"Reply sent to {sid}.")
            time.sleep(2)
            self.fetch_data_worker()
        except Exception as e:
            self.call_from_thread(self.update_status, f"Error sending reply: {e}")
            self.call_from_thread(self.clear_session_answering, sid)

    def action_archive_selected(self) -> None:
        list_view = self.query_one("#session-list", ListView)
        if isinstance(list_view.highlighted_child, SessionItem):
            sid = list_view.highlighted_child.sid
            if self.show_archived:
                self.update_status(f"Unarchiving session {sid}...")
                self.unarchive_worker(sid)
            else:
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

    @work(exclusive=True, thread=True)
    def unarchive_worker(self, sid: str) -> None:
        try:
            unarchive_session(sid)
            self.call_from_thread(self.update_status, f"Unarchived session {sid}.")
            self.fetch_data_worker()
        except Exception as e:
            self.call_from_thread(self.update_status, f"Unarchive error: {e}")

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
    # Safely kill only prior jules_tui python processes (never touch parent shells/WM)
    current_pid = os.getpid()
    try:
        out = subprocess.check_output(["pgrep", "-f", "python3.*jules_tui.py"], text=True)
        for line in out.strip().splitlines():
            try:
                pid = int(line.strip())
                if pid != current_pid:
                    os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
    except Exception:
        pass

    app = JulesTUIApp()
    app.run()


if __name__ == "__main__":
    main()
