#!/usr/bin/env python3
"""Preview-first installer for the Digits context library.

Renders ``context/`` into an immutable, content-addressed release under the
destination home, generates the host's entry file from ``context/bootstrap.md``
(Copilot loads it automatically; for Claude Code the user links it in as a
folder's CLAUDE.md or imports it), and keeps a private ownership receipt, a retained
versions catalog and rollback snapshots. Nothing is written without --apply.
"""

import argparse
import fcntl
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from urllib.parse import quote, unquote

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import install  # noqa: E402  (workbench installer module, same directory)

SOURCE = _HERE / "context"
PRIVATE_ROOT = ".config/digits/context"
FILE_MODE = 0o600
DIR_MODE = 0o700

# Where each agent host gets the generated entry file, the releases and the
# installer's private state. Each host keeps its own receipt, so both can be
# installed side by side. Claude Code does not discover the entry on its own:
# a CLAUDE.md the user chooses imports it (see CLAUDE_IMPORT).
HOSTS = {
    "copilot": {
        "entry": ".copilot/copilot-instructions.md",
        "library": ".copilot/context/digits/releases",
        "state": ".local/state/digits/context",
    },
    "claude": {
        "entry": ".claude/digits/CLAUDE.md",
        "library": ".claude/digits/context/releases",
        "state": ".local/state/digits/context-claude",
    },
}
CLAUDE_IMPORT = "@~/.claude/digits/CLAUDE.md"
SOURCE_NAME_RE = re.compile(r"[A-Za-z0-9_/-]+\.md")


def use_host(name):
    """Point the installer's paths at one host's layout (default: copilot)."""
    global HOST, ENTRY, LIBRARY, STATE, RECEIPT, RETAINED, BACKUPS, RELEASE_FILE_RE, BACKUP_RE
    layout = HOSTS[name]
    HOST = name
    ENTRY = layout["entry"]
    LIBRARY = layout["library"]
    STATE = layout["state"]
    RECEIPT = STATE + "/receipt.json"
    RETAINED = STATE + "/retained.json"
    BACKUPS = STATE + "/backups"
    RELEASE_FILE_RE = re.compile(re.escape(LIBRARY) + r"/[a-f0-9]{16}/[A-Za-z0-9_/-]+\.md")
    BACKUP_RE = re.compile(re.escape(BACKUPS) + r"/[a-f0-9]{32}\.json")


use_host("copilot")
HASH_RE = re.compile(r"[a-f0-9]{64}")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
LEFTOVER_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")
LINK_RE = re.compile(r"\]\(([^\s)#]+\.md)(#[^\s)]*)?\)")

digest = install.digest


def encoded(value):
    """Canonical JSON bytes used for every JSON file the installer writes."""
    text = json.dumps(value, sort_keys=True, indent=2, separators=(",", ": "), ensure_ascii=True)
    return (text + "\n").encode("utf-8")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _ancestors(relative):
    parts = relative.split("/")
    return ["/".join(parts[:index]) for index in range(1, len(parts))]


def _lstat(path):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------------
# Source corpus and rendering


def load_source():
    """Return (version, {relative name: text}) for the current SOURCE."""
    root = Path(SOURCE)
    try:
        meta = json.loads((root / "version.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("Context version file is missing: %s" % (root / "version.json"))
    version = meta.get("version") if isinstance(meta, dict) else None
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError("Context version must be semantic X.Y.Z in %s" % (root / "version.json"))
    sources = {}
    for path in sorted(root.rglob("*.md")):
        name = path.relative_to(root).as_posix()
        parts = name.split("/")
        for index in range(1, len(parts) + 1):
            if (root / "/".join(parts[:index])).is_symlink():
                raise ValueError("Context source symlink refused: %s" % path)
        if not path.is_file():
            continue
        if not SOURCE_NAME_RE.fullmatch(name):
            raise ValueError("Context source name not allowed (letters, digits, _ - / only): %s" % name)
        sources[name] = path.read_text(encoding="utf-8")
    if "bootstrap.md" not in sources:
        raise ValueError("Context bootstrap is missing: %s" % (root / "bootstrap.md"))
    return version, sources


def _file_uri(path):
    return "file://" + quote(str(path), safe="/_.-~")


def render(text, home, release, relative):
    """Fill placeholders and rewrite relative Markdown links into the release."""
    home = Path(home)
    release = Path(release)
    text = text.replace("{{HOME}}", str(home))
    text = text.replace("{{CONTEXT_ROOT}}", str(release))
    text = text.replace("{{PRIVATE_ROOT}}", str(home / PRIVATE_ROOT))
    if LEFTOVER_PLACEHOLDER_RE.search(text):
        raise ValueError("Unknown context placeholder in %s" % relative)

    source_root = Path(SOURCE).resolve()
    base = (Path(SOURCE) / relative).parent

    def rewrite(match):
        target, fragment = match.group(1), match.group(2) or ""
        if ":" in target:
            return match.group(0)
        resolved = (base / unquote(target)).resolve()
        try:
            inside = resolved.relative_to(source_root)
        except ValueError:
            inside = None
        if inside is None or not resolved.is_file():
            raise ValueError("Broken or escaping context link in %s: %s" % (relative, target + fragment))
        return "](" + _file_uri(release / inside.as_posix()) + fragment + ")"

    return LINK_RE.sub(rewrite, text).encode("utf-8")


def fingerprint(home, version, sources):
    blob = encoded({"home": str(home), "source": sources, "version": version})
    return digest(blob)[:16]


def _header(version, snapshot):
    return (
        "<!-- Generated Digits context %s; snapshot %s. "
        "Do not edit this file; change the reviewed source in the Digits repository "
        "and reinstall. -->\n" % (version, snapshot)
    )


def payload(home):
    """Mapping of relative path -> bytes: release files (sorted), then ENTRY."""
    home = Path(home)
    version, sources = load_source()
    snapshot = fingerprint(home, version, sources)
    release_rel = LIBRARY + "/" + snapshot
    release = home / release_rel
    files = {}
    for name in sorted(sources):
        files[release_rel + "/" + name] = render(sources[name], home, release, name)
    entry = _header(version, snapshot).encode("utf-8")
    entry += render(sources["bootstrap.md"], home, release, "bootstrap.md")
    files[ENTRY] = entry
    return files


# ---------------------------------------------------------------------------
# Receipt, retained catalog and ownership verification


def _valid_record(record):
    return (
        isinstance(record, dict)
        and set(record) == {"mode", "sha256"}
        and _is_int(record["mode"])
        and record["mode"] == FILE_MODE
        and isinstance(record["sha256"], str)
        and HASH_RE.fullmatch(record["sha256"]) is not None
    )


def validate_receipt(obj):
    unrecognized = "Unrecognized context receipt; existing files are preserved"
    if not isinstance(obj, dict) or not _is_int(obj.get("format")) or obj.get("format") != 1:
        raise ValueError(unrecognized)
    files = obj.get("files")
    directories = obj.get("directories")
    backup = obj.get("backup")
    if not isinstance(files, dict) or ENTRY not in files:
        raise ValueError(unrecognized)
    if not isinstance(directories, list) or not isinstance(backup, dict):
        raise ValueError(unrecognized)
    backup_path = backup.get("path")
    backup_hash = backup.get("sha256")
    if not isinstance(backup_path, str) or not BACKUP_RE.fullmatch(backup_path):
        raise ValueError(unrecognized)
    if not isinstance(backup_hash, str) or not HASH_RE.fullmatch(backup_hash):
        raise ValueError(unrecognized)
    for name, record in files.items():
        allowed_name = name == ENTRY or RELEASE_FILE_RE.fullmatch(name) is not None
        if not allowed_name or not _valid_record(record):
            raise ValueError("Invalid context ownership record: %s" % name)
    allowed = set()
    for owned in list(files) + [RECEIPT, backup_path]:
        allowed.update(_ancestors(owned))
    for directory in directories:
        if not isinstance(directory, str) or directory not in allowed:
            raise ValueError("Invalid context directory ownership: %r" % (directory,))
    return obj


def _read_private_json(home, relative, what):
    path = install.checked_path(home, relative)
    info = _lstat(path)
    if info is None:
        return None
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != FILE_MODE:
        raise ValueError("Context %s must be a private regular file (mode 0600): %s" % (what, path))
    return json.loads(path.read_bytes().decode("utf-8"))


def read_receipt(home):
    """Return the validated receipt, or None when there is no owned install."""
    obj = _read_private_json(Path(home), RECEIPT, "receipt")
    if obj is None:
        return None
    return validate_receipt(obj)


def _verify(home, files, directories):
    for name in sorted(files):
        record = files[name]
        path = install.checked_path(home, name)
        info = _lstat(path)
        ok = (
            info is not None
            and stat.S_ISREG(info.st_mode)
            and stat.S_IMODE(info.st_mode) == record["mode"]
            and digest(path.read_bytes()) == record["sha256"]
        )
        if not ok:
            raise ValueError("Missing or locally modified context file; preserving it: %s" % path)
    for directory in directories:
        path = install.checked_path(home, directory)
        info = _lstat(path)
        if info is None or not stat.S_ISDIR(info.st_mode):
            raise ValueError("Changed context directory: %s" % path)


def verify_owned(home, receipt):
    """Verify a receipt's owned files and directories (spec 20 section 7.4).

    Returns None, or raises ValueError (containing ``modified`` for a missing or
    changed file).
    """
    _verify(Path(home), receipt["files"], receipt["directories"])


def read_retained(home):
    """Return the verified retained-versions mapping (empty when absent)."""
    home = Path(home)
    obj = _read_private_json(home, RETAINED, "retained catalog")
    if obj is None:
        return {}
    if not isinstance(obj, dict) or not _is_int(obj.get("format")) or obj.get("format") != 1 \
            or not isinstance(obj.get("files"), dict):
        raise ValueError("Invalid retained context catalog: %s" % (home / RETAINED))
    files = obj["files"]
    for name, record in files.items():
        if not RELEASE_FILE_RE.fullmatch(name) or not _valid_record(record):
            raise ValueError("Invalid retained context ownership record: %s" % name)
    _verify(home, files, [])
    return files


# ---------------------------------------------------------------------------
# Planning


def _directories_for(home, write_paths):
    needed = set()
    for relative in write_paths:
        needed.update(_ancestors(relative))
    create = []
    for directory in needed:
        path = install.checked_path(home, directory)
        info = _lstat(path)
        if info is None:
            create.append(directory)
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError("Expected context directory: %s" % path)
    for relative in write_paths:
        path = install.checked_path(home, relative)
        info = _lstat(path)
        if info is not None and not stat.S_ISREG(info.st_mode):
            raise ValueError("Expected regular context file: %s" % path)
    return sorted(create, key=lambda item: (item.count("/"), item))


def _empty_plan(owned_dirs):
    return {"create": [], "writes": {}, "remove": [], "prune": [], "owned_dirs": sorted(owned_dirs)}


def _rollback_plan(home, previous, retained):
    if previous is None:
        raise ValueError("There is no owned context installation to roll back")
    backup_rel = previous["backup"]["path"]
    backup_path = install.checked_path(home, backup_rel)
    info = _lstat(backup_path)
    if (
        info is None
        or not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != FILE_MODE
        or digest(backup_path.read_bytes()) != previous["backup"]["sha256"]
    ):
        raise ValueError("Missing or modified rollback snapshot: %s" % backup_path)
    snapshot = json.loads(backup_path.read_bytes().decode("utf-8"))
    if (
        not isinstance(snapshot, dict)
        or not _is_int(snapshot.get("format"))
        or snapshot.get("format") != 1
        or "entry" not in snapshot
        or "receipt" not in snapshot
    ):
        raise ValueError("Invalid rollback snapshot: %s" % backup_path)
    prior = snapshot["receipt"]
    if prior is not None:
        validate_receipt(prior)
    entry = snapshot["entry"]
    if entry is not None:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("text"), str)
            or not _is_int(entry.get("mode"))
            or not 0 <= entry["mode"] <= 0o777
        ):
            raise ValueError("Invalid rollback entry in %s" % backup_path)
    if prior is not None:
        expected = prior["files"][ENTRY]
        if (
            entry is None
            or digest(entry["text"].encode("utf-8")) != expected["sha256"]
            or entry["mode"] != expected["mode"]
        ):
            raise ValueError("Rollback entry does not match prior ownership in %s" % backup_path)

    kept = dict(retained)
    for name, record in previous["files"].items():
        if name != ENTRY:
            kept[name] = record
    writes = {RETAINED: (encoded({"files": kept, "format": 1}), FILE_MODE)}
    remove = []
    if entry is not None:
        writes[ENTRY] = (entry["text"].encode("utf-8"), entry["mode"])
    else:
        remove.append(ENTRY)
    if prior is not None:
        writes[RECEIPT] = (encoded(prior), FILE_MODE)
    else:
        remove.append(RECEIPT)
    create = _directories_for(home, list(writes))
    return {
        "create": create,
        "writes": writes,
        "remove": sorted(remove),
        "prune": [],
        "owned_dirs": sorted(set(previous["directories"]) | set(create)),
    }


def make_plan(home, adopt_sha256=None, rollback=False):
    """Compute an install/update or rollback plan; writes nothing."""
    home = Path(home)
    if home.is_symlink() or not home.is_dir():
        raise ValueError("Destination home must be an existing non-symlink directory: %s" % home)
    previous = read_receipt(home)
    retained = read_retained(home)
    if previous is not None:
        verify_owned(home, previous)
    if rollback:
        return _rollback_plan(home, previous, retained)

    files = payload(home)
    entry_path = install.checked_path(home, ENTRY)
    entry_info = _lstat(entry_path)
    if previous is None and entry_info is not None:
        if not stat.S_ISREG(entry_info.st_mode):
            raise ValueError("Existing context entry is not a regular file: %s" % entry_path)
        current = digest(entry_path.read_bytes())
        if adopt_sha256 != current:
            raise ValueError(
                "%s exists but is not owned by the Digits context installer. Review it, move "
                "anything that must be preserved into the context source or your private "
                "bindings, then rerun with --adopt-sha256 %s" % (entry_path, current)
            )

    records = dict(retained)
    if previous is not None:
        records.update(previous["files"])
    scheduled = {}
    for name, data in files.items():
        path = install.checked_path(home, name)
        info = _lstat(path)
        if info is not None and name != ENTRY and name not in records:
            raise ValueError("Existing unowned context file; preserving it: %s" % path)
        records[name] = {"mode": FILE_MODE, "sha256": digest(data)}
        if info is None:
            scheduled[name] = (data, FILE_MODE)
        elif not stat.S_ISREG(info.st_mode):
            raise ValueError("Expected regular context file: %s" % path)
        elif stat.S_IMODE(info.st_mode) != FILE_MODE or path.read_bytes() != data:
            scheduled[name] = (data, FILE_MODE)

    previous_dirs = previous["directories"] if previous is not None else []
    if not scheduled:
        return _empty_plan(previous_dirs)

    if entry_info is None:
        entry_snapshot = None
    else:
        entry_snapshot = {
            "mode": stat.S_IMODE(entry_info.st_mode),
            "text": entry_path.read_bytes().decode("utf-8"),
        }
    backup_bytes = encoded({"entry": entry_snapshot, "format": 1, "receipt": previous})
    backup_rel = BACKUPS + "/" + uuid.uuid4().hex + ".json"
    writes = {backup_rel: (backup_bytes, FILE_MODE)}
    writes.update(scheduled)
    create = _directories_for(home, list(writes) + [RECEIPT])
    receipt = {
        "backup": {"path": backup_rel, "sha256": digest(backup_bytes)},
        "directories": sorted(set(previous_dirs) | set(create)),
        "files": records,
        "format": 1,
    }
    validate_receipt(receipt)
    writes[RECEIPT] = (encoded(receipt), FILE_MODE)
    create = _directories_for(home, list(writes))
    return {
        "create": create,
        "writes": writes,
        "remove": [],
        "prune": [],
        "owned_dirs": sorted(set(receipt["directories"]) | set(create)),
    }


# ---------------------------------------------------------------------------
# Command line


CLAUDE_IMPORT_NOTE = (
    "Claude Code does not load the entry on its own, and the installer never edits your "
    "CLAUDE.md files. For the dashboard's chats only, link it into each environment folder "
    "(an import from outside a folder needs a one-time approval per folder):\n"
    "    ln -s ~/.claude/digits/CLAUDE.md ~/<environment>/CLAUDE.md\n"
    "For every chat, add this line to ~/.claude/CLAUDE.md instead:\n"
    "    " + CLAUDE_IMPORT
)


def _parser():
    parser = argparse.ArgumentParser(
        prog="context_install.py",
        description="Preview (default) or apply the Digits context installation.",
    )
    parser.add_argument("--home", default=None, help="destination home (default: your home)")
    parser.add_argument("--host", choices=sorted(HOSTS), default="copilot",
                        help="agent host to install the context for (default: copilot)")
    parser.add_argument("--apply", action="store_true", help="perform the plan instead of previewing")
    parser.add_argument("--rollback", action="store_true", help="restore the latest snapshot")
    parser.add_argument("--adopt-sha256", dest="adopt_sha256", default=None, metavar="HASH",
                        help="adopt the reviewed existing entry whose SHA-256 is HASH")
    return parser


def _apply(home, adopt, rollback):
    descriptor = os.open(str(home), os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0))
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OSError("another context installer is running for %s" % home)
        plan = make_plan(home, adopt_sha256=adopt, rollback=rollback)
        install.show_plan(home, plan)
        install.execute(home, plan)
    finally:
        os.close(descriptor)


def main(argv=None):
    args = _parser().parse_args(argv)
    raw = args.home if args.home is not None else str(Path.home())
    home = Path(os.path.abspath(os.path.expanduser(raw)))
    adopt = None if args.rollback else args.adopt_sha256
    previous_host = HOST
    use_host(args.host)
    try:
        if args.apply:
            _apply(home, adopt, args.rollback)
            if HOST == "claude":
                print("Context updated. Claude Code reads it when a chat starts; running chats keep "
                      "the copy they loaded until you /clear them or start a new chat.")
            else:
                print("Context updated. Idle chats running the plugin's digits-refresh extension reload it "
                      "before their next turn; chats started without it need an idle /restart.")
            print("No chat was restarted.")
        else:
            plan = make_plan(home, adopt_sha256=adopt, rollback=args.rollback)
            install.show_plan(home, plan)
            print("Preview only: no files or sessions changed. Re-run with --apply to make these changes.")
        if HOST == "claude" and not args.rollback:
            print(CLAUDE_IMPORT_NOTE)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print("Context installer: %s" % error, file=sys.stderr)
        return 1
    finally:
        use_host(previous_host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
