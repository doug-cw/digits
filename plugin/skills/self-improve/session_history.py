#!/usr/bin/env python3
"""Bounded, read-only queries over Claude Code chat history.

Copilot CLI skills read earlier chats with its `session_store_sql` tool. Claude
Code has no such tool; it keeps one JSONL transcript per session at
`~/.claude/projects/<slug>/<session id>.jsonl`, where `<slug>` is the directory
the session started in with every non-alphanumeric character replaced by `-`.
This helper answers the questions the digits skills ask of that history and
prints JSON with only the fields they need. It never prints whole transcripts:
every text is cut to `--max-chars` and every listing is paged.

Standard library only (Python 3.9+). Nothing is written anywhere.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECTS_DIR = (
    Path(os.environ["CLAUDE_CONFIG_DIR"]).expanduser() / "projects"
    if os.environ.get("CLAUDE_CONFIG_DIR")
    else Path.home() / ".claude" / "projects"
)
MAX_LIMIT = 200
MAX_CHARS = 4000
SLUG_RE = re.compile(r"[^A-Za-z0-9]")
REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
TITLE_KEYS = (("custom-title", "customTitle"), ("ai-title", "aiTitle"))
ASK_TOOLS = ("AskUserQuestion", "ExitPlanMode")


class Refused(Exception):
    pass


def slug(path):
    return SLUG_RE.sub("-", str(path))


def parse_time(value, end=False):
    """ISO timestamp or YYYY-MM-DD (a bare end date includes the whole day), as UTC."""
    if value is None:
        return None
    text = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            moment = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return moment + timedelta(days=1) - timedelta(microseconds=1) if end else moment
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise Refused(f"not an ISO timestamp or YYYY-MM-DD date: {value!r}")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def under(path, roots):
    if not roots:
        return True
    return any(path == root or path.startswith(root.rstrip("/") + "/") for root in roots)


def records(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def clean(parts):
    text = REMINDER_RE.sub("", "\n".join(parts)).strip()
    if not text or text.startswith("<local-command-"):
        return None
    return text


def block_text(content):
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return None


def answer_text(record, block, tool):
    """Only the user's own words from one answer: never the question, plan or preview."""
    if block.get("is_error"):
        feedback = record.get("userFeedback")
        label = "[plan rejected]" if tool == "ExitPlanMode" else "[questions rejected]"
        return f"{label} {feedback.strip()}" if isinstance(feedback, str) and feedback.strip() else label
    if tool == "ExitPlanMode":
        return "[plan approved]"
    result = record.get("toolUseResult")
    result = result if isinstance(result, dict) else {}
    answers = result.get("answers") if isinstance(result.get("answers"), dict) else {}
    notes = result.get("annotations") if isinstance(result.get("annotations"), dict) else {}
    picked = []
    for question, answer in answers.items():
        if isinstance(answer, list):
            answer = ", ".join(a for a in answer if isinstance(a, str))
        if not isinstance(answer, str):
            continue
        note = (notes.get(question) or {}).get("notes") if isinstance(notes.get(question), dict) else None
        picked.append(f"{answer} (notes: {note})" if isinstance(note, str) and note.strip() else answer)
    return "[answered] " + "; ".join(picked) if picked else "[answered]"


def turn_text(record, asks):
    """(role, kind, text) for one turn of the chat; None for anything else.

    `asks` maps this transcript's AskUserQuestion and ExitPlanMode call ids
    seen so far to the tool; pass one fresh dict per file. User kinds: `prompt`
    (typed at the input), `queued` (typed while the agent was busy) and
    `answer` (a reply to one of those questions or plans). Other tool results, meta and compaction
    records, sub-agent turns, and messages from peers or task notifications
    are not turns. Assistant replies are `reply`.
    """
    kind = record.get("type")
    if record.get("isSidechain"):
        return None
    if kind == "attachment":
        attachment = record.get("attachment")
        if not isinstance(attachment, dict) or attachment.get("type") != "queued_command":
            return None
        origin = attachment.get("origin")
        if not isinstance(origin, dict) or origin.get("kind") != "human":
            return None
        text = clean(block_text(attachment.get("prompt")) or [])
        return ("user", "queued", text) if text else None
    if kind not in ("user", "assistant"):
        return None
    content = (record.get("message") or {}).get("content")
    if kind == "assistant":
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ASK_TOOLS:
                    asks[b.get("id")] = b.get("name")
        text = clean(block_text(content) or [])
        return ("assistant", "reply", text) if text else None
    if record.get("isMeta") or record.get("isCompactSummary"):
        return None
    origin = record.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return None
    if isinstance(content, list):
        answers = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"
                   and b.get("tool_use_id") in asks]
        if answers:
            text = clean([answer_text(record, b, asks[b["tool_use_id"]]) for b in answers])
            return ("user", "answer", text) if text else None
    parts = block_text(content)
    text = clean(parts) if parts is not None else None
    return ("user", "prompt", text) if text else None


def transcripts(projects_dir, roots, since=None):
    """Top-level session transcripts whose project folder could hold one of the roots.

    A file last modified before `since` cannot hold a later record, so it is skipped.
    """
    if not projects_dir.is_dir():
        return
    prefixes = [slug(root) for root in roots]
    for folder in sorted(projects_dir.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        if prefixes and not any(folder.name.startswith(p) for p in prefixes):
            continue
        for path in sorted(folder.glob("*.jsonl")):
            if not path.is_file() or path.is_symlink():
                continue
            if since and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < since:
                continue
            yield path


def summarize(path, roots):
    """Session metadata, or None when the session did not start under a root."""
    cwd = title = None
    titles = {}
    first = last = None
    counts = {"user": 0, "assistant": 0}
    asks = {}
    for record in records(path):
        if cwd is None and record.get("cwd"):
            cwd = record["cwd"]
            if not under(cwd, roots):
                return None
        for kind, key in TITLE_KEYS:
            if record.get("type") == kind and record.get(key):
                titles[kind] = record[key]
        stamp = record.get("timestamp")
        if stamp:
            try:
                moment = parse_time(stamp)
            except Refused:
                moment = None
            if moment:
                first = moment if first is None or moment < first else first
                last = moment if last is None or moment > last else last
        turn = turn_text(record, asks)
        if turn:
            counts[turn[0]] += 1
    if cwd is None or first is None:
        return None
    for kind, _ in TITLE_KEYS:
        if kind in titles:
            title = titles[kind]
            break
    return {
        "session_id": path.stem,
        "cwd": cwd,
        "title": title,
        "created": iso(first),
        "updated": iso(last),
        "user_turns": counts["user"],
        "assistant_turns": counts["assistant"],
    }


def page(items, limit, offset):
    chunk = items[offset:offset + limit]
    following = offset + len(chunk)
    return {"items": chunk, "total": len(items), "next_offset": following if following < len(items) else None}


def cmd_sessions(args):
    since, until = parse_time(args.since), parse_time(args.until, end=True)
    found = []
    for path in transcripts(args.projects_dir, args.root, since):
        info = summarize(path, args.root)
        if info is None:
            continue
        if since and parse_time(info["updated"]) < since.replace(microsecond=0):
            continue
        if until and parse_time(info["created"]) > until:
            continue
        found.append(info)
    found.sort(key=lambda s: (s["updated"], s["session_id"]), reverse=True)
    return page(found, args.limit, args.offset)


def cmd_turns(args):
    since, until = parse_time(args.since), parse_time(args.until, end=True)
    roles = {"user", "assistant"} if args.role == "both" else {args.role}
    terms = [t.casefold() for t in args.grep]
    found = []
    for path in transcripts(args.projects_dir, args.root, since):
        if args.session and path.stem not in args.session:
            continue
        cwd = None
        asks = {}
        for record in records(path):
            if cwd is None and record.get("cwd"):
                cwd = record["cwd"]
                if not under(cwd, args.root):
                    break
            turn = turn_text(record, asks)
            if not turn or turn[0] not in roles:
                continue
            try:
                moment = parse_time(record.get("timestamp"))
            except Refused:
                continue
            if moment is None or (since and moment < since) or (until and moment > until):
                continue
            role, kind, text = turn
            folded = text.casefold()
            if terms and not any(t in folded for t in terms):
                continue
            found.append({
                "session_id": path.stem,
                "cwd": record.get("cwd") or cwd,
                "timestamp": iso(moment),
                "role": role,
                "kind": kind,
                "text": text[:args.max_chars],
                "truncated": len(text) > args.max_chars,
            })
    found.sort(key=lambda t: (t["timestamp"], t["session_id"]), reverse=args.order == "newest")
    return page(found, args.limit, args.offset)


def bounded(maximum):
    def convert(value):
        number = int(value)
        if not 1 <= number <= maximum:
            raise argparse.ArgumentTypeError(f"must be between 1 and {maximum}")
        return number
    return convert


def non_negative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return number


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--projects-dir", type=Path, default=None,
                        help="transcript folder (default: ~/.claude/projects)")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(command, default_limit):
        command.add_argument("--root", action="append", default=[],
                             help="environment root; repeat for several (default: every folder)")
        command.add_argument("--since", help="UTC ISO timestamp or YYYY-MM-DD")
        command.add_argument("--until", help="UTC ISO timestamp or YYYY-MM-DD (whole day)")
        command.add_argument("--limit", type=bounded(MAX_LIMIT), default=default_limit)
        command.add_argument("--offset", type=non_negative, default=0)

    sessions = sub.add_parser("sessions", help="sessions updated since --since and created by --until, newest first")
    common(sessions, 60)
    sessions.set_defaults(handler=cmd_sessions)

    turns = sub.add_parser("turns", help="bounded user prompts, queued prompts and answers, and assistant replies")
    common(turns, 20)
    turns.add_argument("--session", action="append", default=[], help="session id; repeat for several")
    turns.add_argument("--role", choices=("user", "assistant", "both"), default="both")
    turns.add_argument("--grep", action="append", default=[],
                       help="case-insensitive substring; a turn matches if it contains any")
    turns.add_argument("--order", choices=("newest", "oldest"), default="newest")
    turns.add_argument("--max-chars", type=bounded(MAX_CHARS), default=600)
    turns.set_defaults(handler=cmd_turns)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.projects_dir = (args.projects_dir or PROJECTS_DIR).expanduser()
    args.root = [str(Path(r).expanduser()).rstrip("/") or "/" for r in args.root]
    try:
        result = args.handler(args)
    except (Refused, OSError) as error:
        print(f"Session history: {error}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
