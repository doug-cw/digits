#!/usr/bin/env python3
"""Read-only token usage and estimated cost per task, from Claude Code transcripts.

Claude Code records the API `usage` of every assistant message in its session
transcripts (`<projects>/<slug>/<session id>.jsonl`, plus sub-agent transcripts
under `<session id>/subagents/`). This helper sums that usage per request, groups
it by task (session), project, branch, environment, model or day, and prices it
with the bundled `rates.json` (public list prices) or `--rates FILE`.

Costs are list-price estimates: they ignore subscriptions, negotiated discounts,
batch pricing and calls the transcripts do not record. Standard library only
(Python 3.9+). Nothing is written anywhere.
"""

import argparse
import fnmatch
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "digits_session_history", HERE.parent / "self-improve" / "session_history.py")
history = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(history)

RATES_FILE = HERE / "rates.json"
PROJECTS_FILE = Path("~/.config/digits/context/token-projects.json")
DIMENSIONS = ("task", "project", "branch", "env", "model", "day")
TOKEN_FIELDS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")
UNASSIGNED = "unassigned"
MTOK = 1_000_000
MAX_LIMIT = 200
DATE_SUFFIX = re.compile(r"-\d{8}$")


class Refused(Exception):
    pass


def model_key(model):
    """Bare model id: no provider prefix, `[1m]`-style tag or date suffix."""
    text = str(model or "").strip()
    text = re.sub(r"\[.*?\]$", "", text)
    if "claude-" in text:
        text = text[text.index("claude-"):]
    text = text.split("@", 1)[0]
    return DATE_SUFFIX.sub("", text)


def usage_tokens(usage):
    """Token counts by billing category for one `usage` object."""
    def number(value):
        return value if isinstance(value, int) and value > 0 else 0

    created = number(usage.get("cache_creation_input_tokens"))
    split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    one_hour = number(split.get("ephemeral_1h_input_tokens"))
    five_min = number(split.get("ephemeral_5m_input_tokens"))
    if one_hour + five_min != created:
        # No usable split: count every write at the cheaper 5-minute rate.
        one_hour, five_min = 0, created
    tool = usage.get("server_tool_use") if isinstance(usage.get("server_tool_use"), dict) else {}
    return {
        "input": number(usage.get("input_tokens")),
        "output": number(usage.get("output_tokens")),
        "cache_write_5m": five_min,
        "cache_write_1h": one_hour,
        "cache_read": number(usage.get("cache_read_input_tokens")),
        "web_searches": number(tool.get("web_search_requests")),
    }


def price(tokens, model, speed, geo, rates):
    """Estimated USD for one request, or None when the model has no rates."""
    table = rates["models"].get(model)
    if table is None:
        return None
    prompt = tokens["input"] + tokens["cache_write_5m"] + tokens["cache_write_1h"] + tokens["cache_read"]
    tier = table
    for alternative in table.get("tiers", ()):
        if prompt > alternative["prompt_tokens_over"]:
            tier = alternative
    scale = 1.0
    output_rate = tier["output"]
    if speed == "fast":
        fast = table.get("fast")
        if fast is None:
            return None
        scale = fast["input"] / tier["input"]
        output_rate = fast["output"]
    cost = (tokens["input"] * tier["input"] * scale
            + tokens["cache_write_5m"] * tier["cache_write_5m"] * scale
            + tokens["cache_write_1h"] * tier["cache_write_1h"] * scale
            + tokens["cache_read"] * tier["cache_read"] * scale
            + tokens["output"] * output_rate) / MTOK
    if geo and table.get("geo_multipliers", {}).get(geo):
        cost *= table["geo_multipliers"][geo]
    return cost + tokens["web_searches"] * rates.get("web_search_per_request", 0)


def transcript_files(projects_dir, roots, since):
    """(session id, path) for every main and sub-agent transcript that may hold the window."""
    if not projects_dir.is_dir():
        return
    prefixes = [history.slug(root) for root in roots]
    for folder in sorted(projects_dir.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        if prefixes and not any(folder.name.startswith(p) for p in prefixes):
            continue
        paths = [(p.stem, p) for p in folder.glob("*.jsonl")]
        paths += [(p.parent.parent.name, p) for p in folder.glob("*/subagents/*.jsonl")]
        for session, path in sorted(paths, key=lambda item: str(item[1])):
            if not path.is_file() or path.is_symlink():
                continue
            if since and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < since:
                continue
            yield session, path


def collect(projects_dir, roots, since, until, sessions):
    """Return (requests, session facts) for the window.

    Each request is counted once: Claude Code repeats a message's usage on every
    content block it writes, so records sharing a message id and request id
    collapse to the last one seen.
    """
    requests = {}
    facts = {}
    for session, path in transcript_files(projects_dir, roots, since):
        if sessions and session not in sessions:
            continue
        info = facts.setdefault(session, {"env": None, "titles": {}})
        main = path.parent.name != "subagents"
        for record in history.records(path):
            if main:
                for kind, key in history.TITLE_KEYS:
                    if record.get("type") == kind and record.get(key):
                        info["titles"][kind] = record[key]
            if info["env"] is None and main and record.get("cwd"):
                info["env"] = record["cwd"]
            if record.get("type") != "assistant":
                continue
            message = record.get("message") or {}
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            try:
                moment = history.parse_time(record.get("timestamp"))
            except history.Refused:
                continue
            if moment is None or (since and moment < since) or (until and moment > until):
                continue
            tokens = usage_tokens(usage)
            if not any(tokens.values()):
                continue
            ident = (session, message.get("id") or record.get("uuid"), record.get("requestId"))
            requests[ident] = {
                "session": session,
                "timestamp": moment,
                "model": model_key(message.get("model")),
                "speed": usage.get("speed") or "standard",
                "geo": usage.get("inference_geo") or "",
                "cwd": record.get("cwd") or "",
                "branch": record.get("gitBranch") or "",
                "tokens": tokens,
            }
    if roots:
        keep = {s for s, f in facts.items() if f["env"] and history.under(f["env"], roots)}
        requests = {k: v for k, v in requests.items() if v["session"] in keep}
    return list(requests.values()), facts


def title_of(facts):
    for kind, _ in history.TITLE_KEYS:
        if kind in facts["titles"]:
            return facts["titles"][kind]
    return None


def load_projects(path, explicit):
    """Project rules from the private bindings file; [] when it is absent and optional."""
    target = path.expanduser()
    if not target.is_file():
        if explicit:
            raise Refused(f"projects file not found: {target}")
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as error:
        raise Refused(f"projects file is not JSON: {target}: {error}")
    rules = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise Refused(f'projects file needs a "projects" list: {target}')
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("name"):
            raise Refused(f"every project needs a name: {target}")
    return rules


def project_of(request, title, rules):
    """First rule with a matching cwd prefix, branch glob or title glob."""
    for rule in rules:
        if any(history.under(request["cwd"], [str(Path(p).expanduser()).rstrip("/")])
               for p in rule.get("cwd", ())):
            return rule["name"]
        if request["branch"] and any(fnmatch.fnmatchcase(request["branch"], g) for g in rule.get("branch", ())):
            return rule["name"]
        if title and any(fnmatch.fnmatch(title.casefold(), g.casefold()) for g in rule.get("title", ())):
            return rule["name"]
    return UNASSIGNED


def repo_label(cwd):
    return Path(cwd).name if cwd else ""


def empty_totals():
    totals = dict.fromkeys(TOKEN_FIELDS, 0)
    totals.update(requests=0, web_searches=0, cost_usd=0.0, unpriced_requests=0)
    return totals


def add(totals, request, cost):
    for field in TOKEN_FIELDS + ("web_searches",):
        totals[field] += request["tokens"][field]
    totals["requests"] += 1
    if cost is None:
        totals["unpriced_requests"] += 1
    else:
        totals["cost_usd"] += cost


def keys_for(request, facts, rules, dimensions):
    title = title_of(facts)
    values = {
        "task": request["session"],
        "project": project_of(request, title, rules),
        "branch": "%s@%s" % (repo_label(request["cwd"]), request["branch"] or "-"),
        "env": facts["env"] or "",
        "model": request["model"] or "unknown",
        "day": request["timestamp"].strftime("%Y-%m-%d"),
    }
    return tuple(values[d] for d in dimensions), title


def finish(totals):
    totals["cost_usd"] = round(totals["cost_usd"], 4)
    return totals


def cmd_report(args):
    since, until = history.parse_time(args.since), history.parse_time(args.until, end=True)
    rates = json.loads(args.rates.read_text(encoding="utf-8"))
    rules = load_projects(args.projects or PROJECTS_FILE, explicit=args.projects is not None)
    requests, facts = collect(args.projects_dir, args.root, since, until, set(args.session))
    dimensions = args.by or ["task"]
    groups, total, unpriced = {}, empty_totals(), set()
    for request in requests:
        cost = price(request["tokens"], request["model"], request["speed"], request["geo"], rates)
        if cost is None:
            unpriced.add(request["model"] or "unknown")
        key, title = keys_for(request, facts[request["session"]], rules, dimensions)
        group = groups.get(key)
        if group is None:
            group = groups[key] = dict(zip(dimensions, key), sessions=set(), **empty_totals())
            if "task" in dimensions:
                group["title"] = title
        group["sessions"].add(request["session"])
        add(group, request, cost)
        add(total, request, cost)
    items = []
    for group in groups.values():
        group["sessions"] = len(group["sessions"])
        items.append(finish(group))
    items.sort(key=lambda g: (-g["cost_usd"], -g["output"], [str(g[d]) for d in dimensions]))
    chunk = items[args.offset:args.offset + args.limit]
    following = args.offset + len(chunk)
    total["sessions"] = len({r["session"] for r in requests})
    return {
        "by": dimensions,
        "since": history.iso(since),
        "until": history.iso(until),
        "rates": {"source": rates.get("source"), "retrieved": rates.get("retrieved"), "currency": "USD"},
        "items": chunk,
        "total": len(items),
        "next_offset": following if following < len(items) else None,
        "summary": finish(total),
        "unpriced_models": sorted(unpriced),
    }


def table(result):
    """Markdown table for people; JSON stays the default for agents."""
    dims = result["by"]
    head = dims + (["title"] if "task" in dims else []) + [
        "sessions", "requests", "input", "output", "cache write", "cache read", "est. USD"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]

    def row(item, labels):
        cells = labels + [str(item["sessions"]), str(item["requests"]), f'{item["input"]:,}',
                          f'{item["output"]:,}', f'{item["cache_write_5m"] + item["cache_write_1h"]:,}',
                          f'{item["cache_read"]:,}', "%.2f%s" % (item["cost_usd"], "*" if item["unpriced_requests"] else "")]
        return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"

    for item in result["items"]:
        labels = [str(item[d]) for d in dims] + ([str(item.get("title") or "")] if "task" in dims else [])
        lines.append(row(item, labels))
    pad = [""] * (len(dims) - 1 + (1 if "task" in dims else 0))
    lines.append(row(result["summary"], ["**total**"] + pad))
    notes = ["Estimated at list prices from %s (retrieved %s)." % (result["rates"]["source"], result["rates"]["retrieved"])]
    if result["unpriced_models"]:
        notes.append("* includes requests with no rate (%s); their cost is not counted." % ", ".join(result["unpriced_models"]))
    if result["next_offset"] is not None:
        notes.append("Showing %d of %d groups; next --offset %d." % (len(result["items"]), result["total"], result["next_offset"]))
    return "\n".join(lines + [""] + notes) + "\n"


def bounded(maximum):
    def convert(value):
        number = int(value)
        if not 1 <= number <= maximum:
            raise argparse.ArgumentTypeError(f"must be between 1 and {maximum}")
        return number
    return convert


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--projects-dir", type=Path, default=None,
                        help="transcript folder (default: ~/.claude/projects)")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", help="token usage and estimated cost, grouped")
    report.add_argument("--by", action="append", choices=DIMENSIONS,
                        help="group by; repeat to combine (default: task)")
    report.add_argument("--root", action="append", default=[],
                        help="environment root; repeat for several (default: every folder)")
    report.add_argument("--session", action="append", default=[], help="session id; repeat for several")
    report.add_argument("--since", help="UTC ISO timestamp or YYYY-MM-DD")
    report.add_argument("--until", help="UTC ISO timestamp or YYYY-MM-DD (whole day)")
    report.add_argument("--rates", type=Path, default=RATES_FILE, help="rates JSON (default: bundled)")
    report.add_argument("--projects", type=Path, default=None,
                        help="project rules JSON (default: %s when present)" % PROJECTS_FILE)
    report.add_argument("--format", choices=("json", "table"), default="json")
    report.add_argument("--limit", type=bounded(MAX_LIMIT), default=50)
    report.add_argument("--offset", type=lambda v: max(0, int(v)), default=0)
    report.set_defaults(handler=cmd_report)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.projects_dir = (args.projects_dir or history.PROJECTS_DIR).expanduser()
    args.root = [str(Path(r).expanduser()).rstrip("/") or "/" for r in args.root]
    try:
        result = args.handler(args)
    except (Refused, history.Refused, OSError, ValueError, KeyError) as error:
        print(f"Token usage: {error}", file=sys.stderr)
        return 1
    if args.format == "table":
        sys.stdout.write(table(result))
    else:
        json.dump(result, sys.stdout, indent=1, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
