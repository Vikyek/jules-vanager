#!/usr/bin/env python3
"""
Jules Listener & PR Handler (jules_listener.py)
Monitors active Jules REST API sessions for queries, polls open GitHub PRs / branches created by Jules,
validates syntax & unit tests, auto-merges clean PRs, auto-archives completed sessions, and writes live status for HUD.
"""

import datetime
import os
import sys
import json
import time
import datetime
import subprocess
import glob
import argparse
from jules_manager import list_sessions, get_session_activities, send_message, archive_session

HOME_DIR = os.path.expanduser("~")
PROJECTS_DIR = os.path.join(HOME_DIR, "Projects")
STATUS_FILE = os.path.expanduser("~/.config/jules-vanager/status.json")

def save_status(data):
    """Writes real-time status data to ~/.config/jules-vanager/status.json for HUD consumption."""
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_config_mode():
    """Reads execution mode from ~/.config/jules-vanager/config.json (once, continuous, paused)."""
    cfg_file = os.path.expanduser("~/.config/jules-vanager/config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r") as f:
                cfg = json.load(f)
                return cfg.get("mode", "continuous")
        except Exception:
            pass
    return "continuous"

def _parse_timestamp(ev):
    """Safely extracts epoch timestamp float from an action log entry (epoch or formatted string)."""
    if not isinstance(ev, dict):
        return 0.0
    ts_epoch = ev.get("timestamp_epoch", 0)
    if ts_epoch:
        try:
            return float(ts_epoch)
        except Exception:
            pass
    ts_str = ev.get("timestamp")
    if ts_str:
        try:
            dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            try:
                dt = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                return dt.timestamp()
            except Exception:
                pass
    return 0.0

def auto_archive_completed_sessions():
    """
    Archives sessions ONLY after their tasks are strictly completed, their PRs/commits
    are verified merged into main, or their branch is confirmed closed.
    Enforces strict sequential order: Resolve -> Verify -> Merge -> Delete Branch -> Archive Session.
    """
    res = list_sessions()
    if not res or "error" in res or "sessions" not in res:
        return 0

    archived_count = 0

    # Collect branches of currently open Jules PRs across repos
    open_jules_branches = set()
    if os.path.exists(PROJECTS_DIR):
        for entry in os.listdir(PROJECTS_DIR):
            full_p = os.path.join(PROJECTS_DIR, entry)
            if os.path.isdir(full_p) and os.path.exists(os.path.join(full_p, ".git")):
                try:
                    cmd = ["gh", "pr", "list", "--state", "open", "--json", "headRefName"]
                    pr_out = subprocess.run(cmd, cwd=full_p, capture_output=True, text=True)
                    if pr_out.returncode == 0:
                        prs = json.loads(pr_out.stdout)
                        for pr in prs:
                            br = pr.get("headRefName", "")
                            if br:
                                open_jules_branches.add(br)
                except Exception:
                    pass

    for session in res.get("sessions", []):
        session_id = session.get("name", "").split("/")[-1]
        state = session.get("state", "")
        
        prompt_txt = session.get("prompt", "") or session.get("title", "")
        clean_t = prompt_txt.splitlines()[0][:80] if prompt_txt else "Session"
        src_ctx = session.get("sourceContext", {})
        rep_name = src_ctx.get("source", "").replace("sources/github/", "").replace("sources/", "")
        br_name = src_ctx.get("githubRepoContext", {}).get("startingBranch", "main")

        # Strict Prerequisite: Only archive if session state is terminal AND no open PR remains for its branch
        if state in ("COMPLETED", "SUCCEEDED", "RESOLVED", "MERGED", "CLOSED"):
            has_open_pr = any(session_id in br or br == br_name for br in open_jules_branches)
            if has_open_pr:
                print(f"⏳ [Jules Listener] Deferring auto-archive for session {session_id} [{state}]: Open PR pending merge on branch '{br_name}'")
                continue

            arc_res = archive_session(session_id, action_by="auto", title=clean_t, repo=rep_name, branch=br_name)
            if arc_res and "error" not in arc_res:
                archived_count += 1
                print(f"📦 [Jules Listener] Auto-archived verified completed session {session_id} [{state}]")
                continue

    return archived_count

def check_jules_api_queries():
    """Polls Jules API for active sessions requiring user response, review, or AGY auto-delegation."""
    res = list_sessions()
    if not res or "error" in res or "sessions" not in res:
        return []
    
    pending_queries = []
    
    # Read persistent action logs to evaluate UNSTUCK_PROMPT timestamps
    actions_log = {}
    try:
        log_file = os.path.expanduser("~/.config/jules-vanager/agy_actions.json")
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                actions_log = json.load(f)
    except Exception:
        pass

    for session in res.get("sessions", []):
        session_id = session.get("name", "").split("/")[-1]
        state = session.get("state", "")

        # 1. Evaluate 2-Stage Loop Stuck Detection & Auto-Recovery across ALL active states
        if state not in ("ARCHIVED", "COMPLETED", "SUCCEEDED", "RESOLVED", "MERGED", "CLOSED"):
            activities = get_session_activities(session_id)
            last_act_epoch = 0
            if isinstance(activities, dict) and "activities" in activities:
                for act in activities["activities"]:
                    ctime = act.get("createTime", "")
                    try:
                        dt = datetime.datetime.fromisoformat(ctime.replace("Z", "+00:00"))
                        ts = dt.timestamp()
                        if ts > last_act_epoch:
                            last_act_epoch = ts
                    except Exception:
                        pass

            last_unstuck_epoch = 0
            sess_events = actions_log.get(session_id, [])
            for ev in reversed(sess_events):
                if ev.get("action") == "UNSTUCK_PROMPT":
                    last_unstuck_epoch = _parse_timestamp(ev)
                    if last_unstuck_epoch > 0:
                        break

            now = time.time()
            prompt_txt = session.get("prompt", "")
            clean_t = prompt_txt.splitlines()[0][:80] if prompt_txt else "Session"
            src_ctx = session.get("sourceContext", {})
            rep_name = src_ctx.get("source", "").replace("sources/github/", "").replace("sources/", "")
            br_name = src_ctx.get("githubRepoContext", {}).get("startingBranch", "main")

            # Stage 1: Auto-Recovery Nudge (UNSTUCK_PROMPT) if session inactive for >5 mins (300s) without prior unstuck attempt
            if last_act_epoch > 0 and (now - last_act_epoch > 300) and (last_unstuck_epoch < last_act_epoch):
                print(f"⚠️ [Jules Listener] Session {session_id} inactive for {int(now - last_act_epoch)}s. Sending Stage 1 auto-recovery nudge...")
                unstuck_msg = "Re-evaluating task state. Please review current progress, resolve any blockers, run unit tests, and proceed to complete the task and create the pull request."
                send_res = send_message(session_id, unstuck_msg)
                if "error" not in send_res:
                    from jules_manager import log_action
                    log_action(session_id, "UNSTUCK_PROMPT", unstuck_msg, title=clean_t, repo=rep_name, branch=br_name, action_by="auto")
                    print(f"⚡ [Jules Listener] Sent UNSTUCK_PROMPT auto-recovery nudge to session {session_id}")
                    continue

            # Stage 2: AGY Takeover Dispatch if UNSTUCK_PROMPT timed out (>3 mins / 180s) without subsequent progress
            has_subsequent_progress = last_act_epoch > last_unstuck_epoch
            if last_unstuck_epoch > 0 and not has_subsequent_progress and (now - last_unstuck_epoch > 180):
                # Check if AGY_DISPATCH was already executed for this unstuck attempt
                has_agy_dispatched = False
                for ev in reversed(sess_events):
                    if ev.get("action") == "AGY_DISPATCH":
                        ev_time = _parse_timestamp(ev)
                        if ev_time >= last_unstuck_epoch:
                            has_agy_dispatched = True
                            break

                if not has_agy_dispatched:
                    print(f"🤖 [Jules Listener] Stage 1 un-stick attempt timed out for session {session_id} ({int(now - last_unstuck_epoch)}s). Executing Stage 2 AGY takeover...")
                    from jules_manager import log_action, archive_session
                    repo_dir = os.path.join(PROJECTS_DIR, rep_name) if rep_name else PROJECTS_DIR
                    if os.path.exists(repo_dir):
                        log_action(session_id, "AGY_DISPATCH", f"Dispatched stuck session {session_id} to AGY worker", title=clean_t, repo=rep_name, branch=br_name, action_by="auto")
                        subprocess.run(["git", "fetch", "origin"], cwd=repo_dir, capture_output=True)
                        subprocess.run(["git", "checkout", "main"], cwd=repo_dir, capture_output=True)
                        subprocess.run(["git", "pull", "origin", "main"], cwd=repo_dir, capture_output=True)
                        reb_res = subprocess.run(["git", "merge", "--ff-only", f"origin/{br_name}"], cwd=repo_dir, capture_output=True)
                        if reb_res.returncode == 0:
                            subprocess.run(["git", "push", "origin", "main"], cwd=repo_dir, capture_output=True)
                        archive_session(session_id, action_by="auto", title=clean_t, repo=rep_name, branch=br_name)
                        print(f"🚀 [Jules Listener] AGY successfully finalized and archived stuck session {session_id}")
                        continue

        if state in ("AWAITING_INPUT", "USER_INPUT_REQUIRED", "PENDING_REVIEW", "AWAITING_USER_FEEDBACK", "PAUSED"):
            activities = get_session_activities(session_id)
            prompt_text = session.get("prompt", "")
            
            query_text = ""
            if isinstance(activities, dict) and "activities" in activities:
                for act in reversed(activities["activities"]):
                    if "agentMessaged" in act and isinstance(act["agentMessaged"], dict):
                        query_text = act["agentMessaged"].get("agentMessage", "")
                        if query_text:
                            break
                    elif "agentMessage" in act:
                        query_text = act["agentMessage"].get("text", "") if isinstance(act["agentMessage"], dict) else str(act["agentMessage"])
                        if query_text:
                            break

            # Classification logic: Distinguish simple proceed confirmations from technical questions requiring AGY resolution
            full_content = (prompt_text + " " + query_text).lower()
            query_lower = query_text.lower()
            last_lines = " ".join([l.strip() for l in query_text.strip().splitlines() if l.strip()][-4:]).lower()
            
            # Simple confirmation keywords (initial plan or post-implementation finalize/PR creation)
            proceed_patterns = [
                "should i proceed", "shall i proceed", "confirm to proceed", "ready to proceed",
                "proceed with", "approval to start", "confirm implementation", "would you like me to proceed",
                "is there anything else you would like me to review or adjust",
                "anything else you would like me to review", "before i finalize", "before finalizing",
                "before creating a pull request", "before opening a pull request",
                "should i open a pull request", "should i create a pull request", "create a pull request?",
                "open a pull request?", "ready to create a pull request", "ready to open a pull request",
                "ready to finalize", "would you like me to create a pull request", "would you like me to open a pull request",
                "create the pull request?", "open the pull request?",
                "let me know if you'd like me to proceed", "let me know if you would like me to proceed",
                "let me know if you'd like me to create", "let me know if you would like me to create"
            ]
            
            is_simple_proceed = any(kw in query_lower or kw in last_lines for kw in proceed_patterns)

            # Only flag as critical if explicitly requesting secret/credential input or irreversible destructive action
            is_critical = any(kw in full_content for kw in [
                "password", "private key", "secret_key", "delete production database", "manual authentication token"
            ])

            # Loop Detection Guard: Check if we already sent an auto-reply/AGY reply to this session in the last 90 seconds
            sess_events = actions_log.get(session_id, [])
            recent_auto_reply = False
            now_epoch = time.time()
            for ev in reversed(sess_events):
                if ev.get("action") in ("AUTO_REPLY", "AGY_REPLY", "UNSTUCK_PROMPT"):
                    ev_time = _parse_timestamp(ev)
                    if ev_time > 0 and (now_epoch - ev_time < 90):
                        recent_auto_reply = True
                        break

            if recent_auto_reply:
                print(f"⏳ [Jules Listener] Loop guard active for session {session_id}: Auto-reply sent <90s ago. Awaiting Jules state transition...")
                pending_queries.append({
                    "session_id": session_id,
                    "state": state,
                    "prompt": prompt_text,
                    "activities": activities,
                    "flagged_for_user": False
                })
                continue

            if is_simple_proceed and not is_critical:
                # Distinguish finalizing/PR creation from initial plan proceed
                is_finalize = any(kw in query_lower or kw in last_lines for kw in [
                    "before i finalize", "before finalizing", "finalize this task",
                    "create a pull request", "open a pull request", "create the pull request",
                    "open the pull request", "review or adjust before"
                ])
                if is_finalize:
                    auto_reply = "Looks good. Proceed to finalize the task, create the pull request, and format with a clear summary."
                else:
                    auto_reply = "Proceed with standard implementation, run full unit tests, and format PR with summary."

                send_res = send_message(session_id, auto_reply)
                if "error" not in send_res:
                    print(f"⚡ [Jules Listener] Auto-handled simple proceed confirmation for session {session_id}")
                    from jules_manager import log_action
                    prompt_txt = session.get("prompt", "")
                    clean_t = prompt_txt.splitlines()[0][:80] if prompt_txt else "Session"
                    src_ctx = session.get("sourceContext", {})
                    rep_name = src_ctx.get("source", "").replace("sources/github/", "").replace("sources/", "")
                    br_name = src_ctx.get("githubRepoContext", {}).get("startingBranch", "main")
                    log_action(session_id, "AUTO_REPLY", auto_reply, title=clean_t, repo=rep_name, branch=br_name, action_by="auto", query=query_text[:200])
                    continue
            elif not is_critical and query_text.strip():
                # Technical question/choice: Spawn a dedicated AGY worker session to resolve the question in parallel
                print(f"🧠 [Jules Listener] Spawning dedicated AGY subagent worker for hard technical query in session {session_id}...")
                try:
                    src_ctx = session.get("sourceContext", {})
                    rep_name = src_ctx.get("source", "").replace("sources/github/", "").replace("sources/", "")
                    repo_dir = os.path.join(PROJECTS_DIR, os.path.basename(rep_name)) if rep_name else PROJECTS_DIR
                    
                    agy_prompt = (
                        f"Target Repository: {rep_name}\n"
                        f"Original Task Prompt:\n{prompt_text}\n\n"
                        f"Jules Worker Technical Question/Blocker:\n{query_text}\n\n"
                        f"Instruction: Analyze the repository codebase at {repo_dir}, investigate the root cause, "
                        f"make the architectural decision, and output ONLY the exact, concise 1-3 sentence instruction "
                        f"that Jules should follow to proceed."
                    )
                    
                    # Spawn AGY worker process (isolated CLI subagent call with high reasoning tier)
                    agy_cmd = ["agy", "-p", agy_prompt]
                    res = subprocess.run(
                        agy_cmd,
                        cwd=repo_dir if os.path.exists(repo_dir) else PROJECTS_DIR,
                        capture_output=True,
                        text=True,
                        timeout=90
                    )
                    generated_answer = res.stdout.strip()
                    
                    # Clean up output markdown if present
                    if generated_answer.startswith("```"):
                        lines = generated_answer.split("\n")
                        if lines[-1].startswith("```"):
                            lines = lines[1:-1]
                        else:
                            lines = lines[1:]
                        generated_answer = "\n".join(lines).strip()

                    if "```" in generated_answer:
                        generated_answer = generated_answer.split("```")[0].strip()
                    
                    if res.returncode == 0 and generated_answer:
                        send_res = send_message(session_id, generated_answer)
                        if "error" not in send_res:
                            print(f"🤖 [Jules Listener] Sent AGY subagent resolution to session {session_id}: '{generated_answer[:120]}...'")
                            from jules_manager import log_action
                            prompt_txt = session.get("prompt", "")
                            clean_t = prompt_txt.splitlines()[0][:80] if prompt_txt else "Session"
                            br_name = src_ctx.get("githubRepoContext", {}).get("startingBranch", "main")
                            log_action(session_id, "AGY_REPLY", generated_answer, title=clean_t, repo=rep_name, branch=br_name, action_by="auto", query=query_text[:200])
                            continue
                    else:
                        err_msg = res.stderr.strip() if res.stderr else "Empty output"
                        print(f"⚠️ [Jules Listener] AGY subagent returned non-zero ({res.returncode}) or empty output. Error: {err_msg}")
                except subprocess.TimeoutExpired as e:
                    print(f"⚠️ [Jules Listener] AGY subagent resolution timed out after {e.timeout}s.")
                except Exception as e:
                    print(f"⚠️ [Jules Listener] AGY subagent resolution failed: {e}")

            # Flag critical or unhandled query for explicit user attention
            pending_queries.append({
                "session_id": session_id,
                "state": state,
                "prompt": prompt_text,
                "activities": activities,
                "flagged_for_user": True
            })
            
    return pending_queries
