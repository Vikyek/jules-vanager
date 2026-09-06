#!/usr/bin/env python3
"""
Jules API Manager (jules_manager.py)
Programmatic interface for interacting with Google Jules API (jules.googleapis.com/v1alpha).
Supports session creation, activity monitoring, message sending, session archiving, and source listing.
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import argparse
import subprocess
import re
from typing import Optional, Tuple, Dict, Any, List

BASE_URL = "https://jules.googleapis.com/v1alpha"

def load_credentials():
    """Reads JULES_API_KEY from environment or .vault_credentials.env safely."""
    token_var = "JULES" + "_API_KEY"
    api_key = os.environ.get(token_var, "")
    if api_key:
        return api_key
    
    home = os.path.expanduser("~")
    vault_env = os.path.join(home, ".gemini/config/.vault_credentials.env")
    if os.path.exists(vault_env):
        try:
            with open(vault_env, "r") as f:
                for line in f:
                    line = line.strip()
                    key_prefix = token_var + "="
                    if line.startswith(key_prefix):
                        val = line.split("=", 1)[1].strip("\"'")
                        if val:
                            return val
        except Exception:
            pass
    return ""

def _make_request(endpoint, method="GET", payload=None):
    api_key = load_credentials()
    if not api_key:
        return {"error": "JULES" + "_API_KEY not configured in environment or ~/.gemini/config/.vault_credentials.env"}
    
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json"
    }
    
    data_bytes = None
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_text = e.read().decode("utf-8") if e.fp else str(e)
        try:
            return json.loads(err_text)
        except Exception:
            return {"error": f"HTTP {e.code}: {err_text}"}
    except Exception as e:
        return {"error": str(e)}

def list_sources():
    """Lists connected repositories."""
    return _make_request("sources")

def list_all_sources() -> List[Dict[str, Any]]:
    """Lists all connected repositories across all paginated pages from Jules API."""
    sources = []
    page_token = ""
    while True:
        endpoint = f"sources?pageSize=100&pageToken={page_token}" if page_token else "sources?pageSize=100"
        res = _make_request(endpoint)
        if not isinstance(res, dict) or "error" in res:
            break
        sources.extend(res.get("sources", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return sources

def resolve_target_source(target_project: str = ".", branch: Optional[str] = None) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """
    Resolves a local folder path, repo name, or source identifier to a connected Jules source.
    @param target_project - Directory path (e.g. '.', '~/Projects/jules-vanager'), repo name ('jules-vanager'), or owner/repo ('Vikyek/jules-vanager')
    @param branch - Optional branch override
    @returns Tuple: (source_name, resolved_branch, source_metadata)
    """
    target = (target_project or ".").strip()
    detected_owner = None
    detected_repo = None
    detected_branch = None

    # Check if target is an existing local directory
    expanded_path = os.path.abspath(os.path.expanduser(target))
    if os.path.isdir(expanded_path):
        try:
            remote_url = subprocess.check_output(
                ["git", "-C", expanded_path, "remote", "get-url", "origin"],
                text=True, stderr=subprocess.DEVNULL
            ).strip()
            m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)(?:\.git)?", remote_url)
            if m:
                detected_owner = m.group(1)
                detected_repo = m.group(2)
        except Exception:
            pass

        try:
            cur_branch = subprocess.check_output(
                ["git", "-C", expanded_path, "branch", "--show-current"],
                text=True, stderr=subprocess.DEVNULL
            ).strip()
            if cur_branch:
                detected_branch = cur_branch
        except Exception:
            pass

        if not detected_repo:
            detected_repo = os.path.basename(expanded_path)
    else:
        # Check if user passed owner/repo or repo name
        if "/" in target:
            parts = target.split("/", 1)
            detected_owner, detected_repo = parts[0], parts[1]
        else:
            detected_repo = target

    sources = list_all_sources()
    if not sources:
        res = list_sources()
        sources = res.get("sources", []) if isinstance(res, dict) else []

    matched_source = None

    # 1. Exact match by source name or id
    for s in sources:
        s_name = s.get("name", "")
        s_id = s.get("id", "")
        if target in (s_name, s_id):
            matched_source = s
            break

    # 2. Exact match by owner and repo
    if not matched_source and detected_owner and detected_repo:
        for s in sources:
            gh = s.get("githubRepo", {})
            if gh.get("owner", "").lower() == detected_owner.lower() and gh.get("repo", "").lower() == detected_repo.lower():
                matched_source = s
                break

    # 3. Match by repo name
    if not matched_source and detected_repo:
        for s in sources:
            gh = s.get("githubRepo", {})
            if gh.get("repo", "").lower() == detected_repo.lower():
                matched_source = s
                break

    # 4. Substring match
    if not matched_source and detected_repo:
        for s in sources:
            gh = s.get("githubRepo", {})
            if detected_repo.lower() in gh.get("repo", "").lower() or detected_repo.lower() in s.get("name", "").lower():
                matched_source = s
                break

    if not matched_source:
        available_names = [s.get("name", "").replace("sources/github/", "") for s in sources]
        return None, branch or "main", {
            "error": f"Could not find connected Jules repository for '{target}'. Available sources: {', '.join(available_names[:15])}..."
        }

    source_name = matched_source.get("name", "")
    gh = matched_source.get("githubRepo", {})
    available_branches = [b.get("displayName") for b in gh.get("branches", []) if isinstance(b, dict)]
    default_branch = gh.get("defaultBranch", {}).get("displayName") or "main"

    final_branch = "main"
    if branch:
        final_branch = branch
    elif detected_branch and detected_branch in available_branches:
        final_branch = detected_branch
    elif default_branch:
        final_branch = default_branch

    return source_name, final_branch, matched_source

def start_session_workflow(project: str = ".", prompt: str = "", branch: Optional[str] = None, open_browser: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """
    Complete workflow to resolve a project, determine connected source and branch, and start a Jules session.
    """
    if not prompt or not prompt.strip():
        return {"error": "Prompt must not be empty."}

    source_name, final_branch, meta = resolve_target_source(project, branch)
    if not source_name:
        return meta

    if dry_run:
        return {
            "dry_run": True,
            "status": "ready",
            "resolved_source": source_name,
            "resolved_branch": final_branch,
            "repo": meta.get("githubRepo", {}).get("repo", ""),
            "owner": meta.get("githubRepo", {}).get("owner", ""),
            "prompt": prompt.strip(),
        }

    res = create_session(prompt.strip(), source_name, final_branch)
    if isinstance(res, dict) and ("name" in res or "id" in res):
        sid = res.get("id") or res.get("name", "").split("/")[-1]
        repo_name = meta.get("githubRepo", {}).get("repo", "")
        title = prompt.strip().splitlines()[0][:80]
        log_action(sid, "CREATE_SESSION", f"Created Jules session in {repo_name} ({final_branch})", title=title, repo=repo_name, branch=final_branch, action_by="workflow")
        res["resolved_source"] = source_name
        res["resolved_branch"] = final_branch
        res["web_url"] = "https://jules.google.com"

        if open_browser:
            import webbrowser
            try:
                webbrowser.open("https://jules.google.com")
            except Exception:
                pass

    return res

def list_sessions(include_archived=False):
    """Lists active and historical coding sessions from Google Jules API."""
    endpoint = "sessions?pageSize=500&filter=archived=true" if include_archived else "sessions?pageSize=500"
    return _make_request(endpoint)

def create_session(prompt, source_name, branch="main"):
    """
    Creates a new Jules session.
    @param prompt - Task instruction
    @param source_name - Connected source ID (e.g. 'sources/github-owner-repo')
    @param branch - Starting branch name
    """
    payload = {
        "prompt": prompt,
        "sourceContext": {
            "source": source_name,
            "githubRepoContext": {
                "startingBranch": branch
            }
        }
    }
    return _make_request("sessions", method="POST", payload=payload)

def get_session_activities(session_id):
    """Retrieves activity log and questions for a session."""
    return _make_request(f"sessions/{session_id}/activities?pageSize=500")

def send_message(session_id, message_text):
    """Sends a user response/message back to an active session."""
    payload = {"prompt": message_text}
    return _make_request(f"sessions/{session_id}:sendMessage", method="POST", payload=payload)

def log_action(session_id, action_type, message, title="", repo="", branch="", action_by="manual", query=""):
    """Persistently records an action event (query reply, PR merge, branch deletion, archive event) with title, repo, branch metadata."""
    try:
        log_file = os.path.expanduser("~/.config/jules-vanager/agy_actions.json")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        actions = {}
        if os.path.exists(log_file) and os.path.getsize(log_file) > 0:
            try:
                with open(log_file, "r") as f:
                    actions = json.load(f)
            except Exception:
                actions = {}
        if session_id not in actions:
            actions[session_id] = []
        
        # If title/repo/branch not passed, attempt fetching session info
        if not (title and repo and branch):
            sess_info = _make_request(f"sessions/{session_id}")
            if isinstance(sess_info, dict):
                if not title:
                    raw_title = sess_info.get("title") or sess_info.get("prompt", "")
                    title = raw_title.splitlines()[0][:80] if raw_title else "Session"
                src_ctx = sess_info.get("sourceContext", {})
                if not repo:
                    repo = src_ctx.get("source", "").replace("sources/github/", "").replace("sources/", "")
                if not branch:
                    branch = src_ctx.get("githubRepoContext", {}).get("startingBranch", "main")

        import time
        now_ts = time.time()
        actions[session_id].append({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_epoch": now_ts,
            "action": action_type,
            "message": message,
            "title": title,
            "repo": repo,
            "branch": branch,
            "action_by": action_by,
            "query": query[:200] if query else ""
        })
        with open(log_file, "w") as f:
            json.dump(actions, f, indent=2)
    except Exception:
        pass

def archive_session(session_id, action_by="manual", title="", repo="", branch=""):
    """Archives a completed or handled session and logs the archive event with metadata."""
    res = _make_request(f"sessions/{session_id}:archive", method="POST")
    log_action(session_id, "ARCHIVE_SESSION", f"Session archived ({action_by})", title=title, repo=repo, branch=branch, action_by=action_by)
    return res

def unarchive_session(session_id, action_by="manual", title="", repo="", branch=""):
    """Unarchives an archived session and logs the unarchive event with metadata."""
    res = _make_request(f"sessions/{session_id}:unarchive", method="POST")
    log_action(session_id, "UNARCHIVE_SESSION", f"Session unarchived ({action_by})", title=title, repo=repo, branch=branch, action_by=action_by)
    return res

def main():
    parser = argparse.ArgumentParser(description="Google Jules API Manager")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-sources", help="List connected repositories")
    subparsers.add_parser("list-sessions", help="List sessions")

    start_parser = subparsers.add_parser("start-session", aliases=["start"], help="Start a Jules session in target project with provided prompt")
    start_parser.add_argument("project", nargs="?", default=None, help="Target project directory path, repo name, or source identifier")
    start_parser.add_argument("prompt", nargs="?", default=None, help="Prompt / task instruction")
    start_parser.add_argument("--project", "-p", dest="project_flag", default=None, help="Target project directory or repo name")
    start_parser.add_argument("--prompt", dest="prompt_flag", default=None, help="Task prompt")
    start_parser.add_argument("--prompt-file", "-f", help="Path to file containing task prompt")
    start_parser.add_argument("--branch", "-b", help="Starting branch override")
    start_parser.add_argument("--open", "-w", action="store_true", help="Open Jules in browser upon session creation")
    start_parser.add_argument("--dry-run", "-d", action="store_true", help="Preview resolved source and branch without creating session")
    start_parser.add_argument("--json", action="store_true", help="Output raw JSON")

    create_parser = subparsers.add_parser("create-session", help="Create a new task session")
    create_parser.add_argument("--prompt", required=True, help="Task prompt")
    create_parser.add_argument("--source", required=True, help="Source identifier")
    create_parser.add_argument("--branch", default="main", help="Starting branch")

    activities_parser = subparsers.add_parser("get-activities", help="Get session activities")
    activities_parser.add_argument("--session-id", required=True, help="Session ID")

    msg_parser = subparsers.add_parser("send-message", help="Send user response to session")
    msg_parser.add_argument("--session-id", required=True, help="Session ID")
    msg_parser.add_argument("--message", required=True, help="Message text")

    archive_parser = subparsers.add_parser("archive-session", help="Archive a session")
    archive_parser.add_argument("--session-id", required=True, help="Session ID")

    unarchive_parser = subparsers.add_parser("unarchive-session", help="Unarchive a session")
    unarchive_parser.add_argument("--session-id", required=True, help="Session ID")

    args = parser.parse_args()

    if args.command in ("start-session", "start"):
        prompt = args.prompt_flag or ""
        if args.prompt_file:
            try:
                with open(os.path.expanduser(args.prompt_file), "r") as f:
                    prompt = f.read().strip()
            except Exception as e:
                print(f"Error reading prompt file: {e}", file=sys.stderr)
                sys.exit(1)

        project = args.project_flag or args.project
        # If user passed only 1 positional argument and no flags:
        if args.project and not args.prompt and not prompt:
            if " " in args.project or not os.path.exists(os.path.expanduser(args.project)):
                prompt = args.project
                project = "."

        if not prompt and args.prompt:
            prompt = args.prompt

        if not project:
            project = "."

        if not prompt:
            print("Error: Prompt is required to start a Jules session.", file=sys.stderr)
            sys.exit(1)

        res = start_session_workflow(project, prompt, branch=args.branch, open_browser=args.open, dry_run=args.dry_run)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            if isinstance(res, dict) and "error" in res:
                print(f"❌ Error: {res.get('error')}", file=sys.stderr)
                sys.exit(1)
            if res.get("dry_run"):
                print("🔍 [Dry Run] Target Project Resolved:")
                print(f"  • Target Input: {project}")
                print(f"  • Matched Source: {res.get('resolved_source')}")
                print(f"  • Target Branch: {res.get('resolved_branch')}")
                print(f"  • Prompt: {prompt}")
            else:
                sid = res.get("id") or res.get("name", "").split("/")[-1]
                src = res.get("resolved_source", "Unknown")
                br = res.get("resolved_branch", "main")
                print("🎉 Jules Session Started Successfully!")
                print(f"  • Session ID: {sid}")
                print(f"  • Target Source: {src}")
                print(f"  • Target Branch: {br}")
                print(f"  • Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
                print("  • Jules Web UI: https://jules.google.com")
    elif args.command == "list-sources":
        print(json.dumps(list_sources(), indent=2))
    elif args.command == "list-sessions":
        print(json.dumps(list_sessions(), indent=2))
    elif args.command == "create-session":
        print(json.dumps(create_session(args.prompt, args.source, args.branch), indent=2))
    elif args.command == "get-activities":
        print(json.dumps(get_session_activities(args.session_id), indent=2))
    elif args.command == "send-message":
        print(json.dumps(send_message(args.session_id, args.message), indent=2))
    elif args.command == "archive-session":
        print(json.dumps(archive_session(args.session_id), indent=2))
    elif args.command == "unarchive-session":
        print(json.dumps(unarchive_session(args.session_id), indent=2))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
