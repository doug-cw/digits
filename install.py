"""Preview-first installer and remover for the Digits workbench.

Run ``python3 install.py`` to preview, add ``--apply`` to make changes and
``--uninstall`` to remove what this installer owns.  The module is also
imported by ``context_install.py``, which reuses ``digest``, ``checked_path``,
``atomic_write``, ``execute`` and ``show_plan``.  Importing it has no side
effects.
"""

import argparse
import fcntl
import hashlib
import json
import os
import platform
import shutil
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parent

# (repository source, destination relative to home, installed mode), in
# installer table order.
COMMON_FILES = (
    ("bin/ai-agents", ".local/bin/ai-agents", 0o755),
    ("bin/md-view", ".local/bin/md-view", 0o755),
    ("terminal/ai-agents.conf", ".tmux/ai-agents.conf", 0o644),
)

# Files that connect one agent host's chats to the dashboard (--host).
HOST_FILES = {
    "copilot": (
        (
            "copilot/extensions/env-dashboard/extension.mjs",
            ".copilot/extensions/env-dashboard/extension.mjs",
            0o644,
        ),
        (
            "copilot/extensions/env-dashboard/state.mjs",
            ".copilot/extensions/env-dashboard/state.mjs",
            0o644,
        ),
    ),
    "claude": (
        (
            "claude/hooks/env_dashboard.py",
            ".claude/hooks/digits-env-dashboard.py",
            0o755,
        ),
        ("claude/bin/digits-claude", ".local/bin/digits-claude", 0o755),
    ),
}
HOSTS = tuple(HOST_FILES)
CLAUDE_HOOK = ".claude/hooks/digits-env-dashboard.py"
DEFAULT_HOST = "copilot"


def files_for(host=DEFAULT_HOST):
    """The installer table for one host: the common files, then the host's."""
    if host not in HOST_FILES:
        raise ValueError("Unknown host: {}".format(host))
    return COMMON_FILES + HOST_FILES[host]


FILES = files_for(DEFAULT_HOST)

RECEIPT = ".local/state/digits/dashboard.json"
RECEIPT_MODE = 0o600
RECEIPT_VERSION = 1
FILE_MODES = (0o644, 0o755)

ENVIRONMENTS = (
    "left_pinky",
    "left_ring",
    "left_middle",
    "left_pointer",
    "left_thumb",
    "right_thumb",
    "right_pointer",
    "right_middle",
    "right_ring",
    "right_pinky",
)

PREREQUISITES = ("tmux", "node", "copilot")
HOST_PREREQUISITES = {"copilot": PREREQUISITES, "claude": ("tmux", "claude", "python3")}


def _depth_key(relative):
    return (len(PurePosixPath(relative).parts), relative)


def _ancestors(relative):
    parts = PurePosixPath(relative).parts[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def _managed_directories(files):
    found = set(ENVIRONMENTS)
    for _source, destination, _mode in files:
        found.update(_ancestors(destination))
    found.update(_ancestors(RECEIPT))
    return sorted(found, key=_depth_key)


ALL_FILES = COMMON_FILES + tuple(entry for host in HOSTS for entry in HOST_FILES[host])
# Everything any host may own; a receipt is valid when it stays within this.
MANAGED_DIRECTORIES = tuple(_managed_directories(ALL_FILES))
MANAGED_FILES = tuple(destination for _source, destination, _mode in ALL_FILES)


# --- Shared low-level helpers (also used by context_install.py) -------------


def digest(data):
    """Return the lowercase hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def checked_path(home, relative):
    """Return ``home / relative`` after refusing symlinks and non-directory parents."""
    home = Path(home)
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError("Path must be relative to home: {}".format(relative))
    current = home
    last = len(pure.parts) - 1
    for index, part in enumerate(pure.parts):
        current = current / part
        try:
            info = os.lstat(str(current))
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Refusing symlink: {}".format(current))
        if index < last and not stat.S_ISDIR(info.st_mode):
            raise ValueError("Parent is not a directory: {}".format(current))
    return home.joinpath(*pure.parts)


def atomic_write(path, data, mode):
    """Atomically replace ``path`` with ``data`` and exact permission ``mode``."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".digits-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)
        os.replace(temporary, str(path))
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _prior_state(path):
    """Return (bytes, mode) of an existing regular file, or None if absent."""
    try:
        info = os.lstat(str(path))
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Destination is not a regular file: {}".format(path))
    return path.read_bytes(), stat.S_IMODE(info.st_mode)


def _is_empty_directory(path):
    try:
        with os.scandir(str(path)) as entries:
            return next(entries, None) is None
    except FileNotFoundError:
        return False


def execute(home, plan):
    """Apply ``plan`` under ``home``, rolling back on any failure."""
    home = Path(home)
    created = []
    journal = []
    try:
        for relative in plan.get("create", []):
            path = checked_path(home, relative)
            if path.is_dir():
                continue
            os.mkdir(str(path), 0o700)
            created.append(path)
        for relative, (data, mode) in plan.get("writes", {}).items():
            path = checked_path(home, relative)
            journal.append((path, _prior_state(path)))
            atomic_write(path, data, mode)
        for relative in plan.get("remove", []):
            path = checked_path(home, relative)
            journal.append((path, _prior_state(path)))
            os.unlink(str(path))
    except (OSError, ValueError) as error:
        failures = []
        for path, prior in reversed(journal):
            try:
                if prior is None:
                    try:
                        os.unlink(str(path))
                    except FileNotFoundError:
                        pass
                else:
                    atomic_write(path, prior[0], prior[1])
            except Exception as undo_error:  # noqa: BLE001 - collect every failure
                failures.append("{}: {}".format(path, undo_error))
        for path in reversed(created):
            try:
                if not path.exists():
                    continue
                if _is_empty_directory(path):
                    os.rmdir(str(path))
                else:
                    print("KEEP non-empty directory {}".format(path))
            except OSError as undo_error:
                failures.append("{}: {}".format(path, undo_error))
        if failures:
            raise RuntimeError(
                "{}; rollback incomplete: {}".format(error, "; ".join(failures))
            ) from error
        raise
    for relative in sorted(plan.get("prune", []), key=_depth_key, reverse=True):
        path = checked_path(home, relative)
        if not path.exists():
            continue
        if _is_empty_directory(path):
            os.rmdir(str(path))
        else:
            print("KEEP non-empty directory {}".format(path))


def show_plan(home, plan):
    """Print the planned actions with absolute paths."""
    home = Path(home)
    for relative in plan.get("create", []):
        print("CREATE directory {}".format(home / relative))
    for relative in plan.get("writes", {}):
        print("WRITE {}".format(home / relative))
    for relative in plan.get("remove", []):
        print("REMOVE {}".format(home / relative))
    for relative in plan.get("prune", []):
        print("REMOVE directory if empty {}".format(home / relative))
    if not plan.get("create") and not plan.get("writes") and not plan.get("remove"):
        print("No file changes needed.")


# --- Workbench planning ------------------------------------------------------


def _validate_home(home):
    home = Path(home)
    if home.is_symlink() or not home.is_dir():
        raise ValueError(
            "Home must be an existing directory and not a symlink: {}".format(home)
        )
    return home


def _is_hex_digest(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def read_receipt(home):
    """Return the validated receipt dict, or None when there is no receipt."""
    path = checked_path(home, RECEIPT)
    try:
        info = os.lstat(str(path))
    except FileNotFoundError:
        return None
    unrecognized = "Unrecognized installation receipt: {}".format(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(unrecognized)
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError(unrecognized) from None
    if not isinstance(receipt, dict):
        raise ValueError(unrecognized)
    version = receipt.get("version")
    if isinstance(version, bool) or version != RECEIPT_VERSION:
        raise ValueError(unrecognized)
    files = receipt.get("files")
    directories = receipt.get("directories")
    if not isinstance(files, dict) or not set(files) <= set(MANAGED_FILES):
        raise ValueError(unrecognized)
    if not isinstance(directories, list) or not all(
        isinstance(item, str) and item in MANAGED_DIRECTORIES for item in directories
    ):
        raise ValueError(unrecognized)
    for relative, record in files.items():
        if (
            not isinstance(record, dict)
            or not _is_hex_digest(record.get("sha256"))
            or not isinstance(record.get("mode"), int)
            or isinstance(record.get("mode"), bool)
            or record.get("mode") not in FILE_MODES
        ):
            raise ValueError("Invalid file record in receipt: {}".format(relative))
    return receipt


def _empty_plan():
    return {"create": [], "writes": {}, "remove": [], "prune": []}


def build_plan(home, uninstall=False, source=None, host=DEFAULT_HOST):
    """Compute the install (or uninstall) plan for ``home``.

    An install writes the common files and ``host``'s files. Files owned for
    another host are left in place and stay in the receipt, so switching hosts
    never orphans them; an uninstall removes everything the receipt owns.
    """
    files = files_for(host)
    home = _validate_home(home)
    source = Path(source) if source is not None else REPO
    receipt = read_receipt(home)
    if receipt is not None:
        for relative in receipt["directories"]:
            path = checked_path(home, relative)
            if os.path.lexists(str(path)) and not path.is_dir():
                raise ValueError("Expected an installed directory: {}".format(path))
    if uninstall and receipt is None:
        return _empty_plan()

    owned = receipt["files"] if receipt is not None else {}
    plan = _empty_plan()
    new_files = {}
    for source_relative, relative, mode in (ALL_FILES if uninstall else files):
        if uninstall and relative not in owned:
            continue
        path = checked_path(home, relative)
        existing = _prior_state(path)
        if existing is not None:
            if relative not in owned:
                raise ValueError(
                    "Existing unowned file; merge manually instead: {}".format(path)
                )
            record = owned[relative]
            if digest(existing[0]) != record["sha256"] or existing[1] != record["mode"]:
                raise ValueError("Locally modified file; preserving it: {}".format(path))
        if uninstall:
            continue
        data = (source / source_relative).read_bytes()
        new_files[relative] = {"sha256": digest(data), "mode": mode}
        if existing is None or existing[0] != data or existing[1] != mode:
            plan["writes"][relative] = (data, mode)

    if uninstall:
        for relative in owned:
            if os.path.lexists(str(checked_path(home, relative))):
                plan["remove"].append(relative)
        plan["remove"].append(RECEIPT)
        plan["prune"] = list(receipt["directories"])
        return plan

    for relative in owned:
        if relative not in new_files:
            new_files[relative] = owned[relative]

    for relative in _managed_directories(files):
        path = checked_path(home, relative)
        if not os.path.lexists(str(path)):
            plan["create"].append(relative)
        elif not path.is_dir():
            raise ValueError("Expected a directory: {}".format(path))
    plan["create"].sort(key=_depth_key)
    previous = receipt["directories"] if receipt is not None else []
    new_receipt = {
        "version": RECEIPT_VERSION,
        "files": new_files,
        "directories": sorted(set(previous) | set(plan["create"])),
    }
    receipt_bytes = (json.dumps(new_receipt, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    current = _prior_state(checked_path(home, RECEIPT))
    if current is None or current[0] != receipt_bytes or current[1] != RECEIPT_MODE:
        plan["writes"][RECEIPT] = (receipt_bytes, RECEIPT_MODE)
    return plan


# --- Command line ------------------------------------------------------------


def check_prerequisites(host=DEFAULT_HOST):
    """Fail unless running on macOS with the host's required commands on PATH."""
    if platform.system() != "Darwin":
        raise ValueError("Only macOS is supported.")
    missing = [name for name in HOST_PREREQUISITES[host] if shutil.which(name) is None]
    if missing:
        raise ValueError(
            "Please install these commands first: {}".format(", ".join(missing))
        )


def _parse(argv):
    parser = argparse.ArgumentParser(
        description="Preview, install or remove the Digits workbench files."
    )
    parser.add_argument("--apply", action="store_true", help="perform the previewed changes")
    parser.add_argument("--uninstall", action="store_true", help="remove the installed files")
    parser.add_argument("--home", help="destination home directory (default: your home)")
    parser.add_argument(
        "--host", choices=HOSTS, default=DEFAULT_HOST,
        help="agent host whose chats feed the dashboard (default: copilot)",
    )
    return parser.parse_args(argv)


def _run(args):
    if args.home:
        home = Path(os.path.abspath(os.path.expanduser(args.home)))
    else:
        home = Path(os.path.abspath(str(Path.home())))
    if not args.uninstall:
        check_prerequisites(args.host)
    if not args.apply:
        show_plan(home, build_plan(home, args.uninstall, host=args.host))
        if args.host == "claude" and not args.uninstall:
            print(CLAUDE_HOOKS_NOTE)
        print("Preview only. Re-run with --apply to make changes.")
        return
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(str(home), flags)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = build_plan(home, args.uninstall, host=args.host)
        show_plan(home, plan)
        execute(home, plan)
    finally:
        os.close(descriptor)
    if args.uninstall:
        print("Removed unchanged owned files; running sessions were not stopped.")
        print("Reload or restart idle Copilot chats to unload the dashboard extension.")
        if CLAUDE_HOOK in plan.get("remove", []):
            print("Remove the Digits hooks from ~/.claude/settings.json if you added them.")
    elif args.host == "claude":
        print("Installed. Launch from your terminal: {}".format(home / ".local/bin/ai-agents"))
        print(CLAUDE_HOOKS_NOTE)
    else:
        print("Installed. Launch from your terminal: {}".format(home / ".local/bin/ai-agents"))
        print(
            "No session was started; restart or reload existing Copilot chats "
            "while idle to load the dashboard extension."
        )


CLAUDE_HOOKS_NOTE = (
    "Claude Code: this installer never edits your settings. Merge the hooks in "
    "claude/settings.json into ~/.claude/settings.json yourself, then start new "
    "Claude Code chats (running ones keep the hooks they started with). Start them "
    "with digits-claude, which names each chat after its environment and loads the "
    "plugin from DIGITS_PLUGIN_DIR when set."
)


def main(argv=None):
    args = _parse(argv)
    try:
        _run(args)
    except (OSError, ValueError, RuntimeError) as error:
        print("Dashboard installer: {}".format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
