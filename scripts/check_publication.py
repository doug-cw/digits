#!/usr/bin/env python3
"""Publication preflight: check what a push or a PR text would publish.

``--range <rev-range>`` (repeatable) inspects every commit in the range: author and
committer emails must be GitHub noreply addresses, ``*-by:`` trailer emails
must be noreply addresses, and the names, full message, changed paths and
added lines are scanned for private terms (shared with the repository guard),
machine home paths and email addresses outside the reserved example domains;
binary changes are reported because they cannot be inspected.
``--text <file|->`` scans PR or issue text the same way. Added lines, messages
and texts also go through detect-secrets, which is required.

Findings name a location and a kind, never the matched value. Exit status is
0 when clean and 1 on findings or configuration errors.

Run as ``python scripts/check_publication.py --range <base>..HEAD``.
"""

import argparse
import codecs
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from scripts import check_repository as _repository_guard
    from scripts import check_secrets as _secret_guard
except ImportError:  # executed directly: the scripts directory is on sys.path
    import check_repository as _repository_guard
    import check_secrets as _secret_guard

ROOT = Path(__file__).resolve().parent.parent

SCANNER = _secret_guard.SCANNER
HOME_PATH = _repository_guard.HOME_PATH

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
GITHUB_NOREPLY = re.compile(
    r"^(?:[^@\s]+@users\.noreply\.github\.com|noreply@github\.com)$", re.IGNORECASE
)
TRAILER_NOREPLY = frozenset({"noreply@anthropic.com"})
EXAMPLE_DOMAINS = frozenset({"example.com", "example.net", "example.org"})
EXAMPLE_TLDS = frozenset({"example", "invalid", "localhost", "test"})
TRAILER = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]*-by)\s*:", re.IGNORECASE)

# Explicit prefixes override diff.noprefix, diff.mnemonicPrefix and friends.
GIT_DIFF_OPTIONS = [
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--no-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
]
# detect-secrets picks keyword rules by these suffixes; others are scanned as .txt
# (a source suffix such as .css or .lock would make it skip the file).
KEYWORD_SUFFIXES = frozenset(
    {
        ".c", ".cf", ".cfg", ".cls", ".cnf", ".conf", ".cpp", ".cs", ".eyaml",
        ".go", ".ini", ".java", ".js", ".m", ".properties", ".py", ".pyi",
        ".swift", ".tf", ".toml", ".yaml", ".yml",
    }
)


class PreflightError(RuntimeError):
    """Git or the input could not be read; no passing result is claimed."""


def is_github_noreply(address):
    return GITHUB_NOREPLY.match(address) is not None


def is_trailer_noreply(address):
    return is_github_noreply(address) or address.casefold() in TRAILER_NOREPLY


def is_publishable_email(address):
    """True for noreply addresses and the reserved example domains."""
    if is_trailer_noreply(address):
        return True
    domain = address.rsplit("@", 1)[1].casefold().rstrip(".")
    labels = domain.split(".")
    if labels[-1] in EXAMPLE_TLDS:
        return True
    return any(domain == d or domain.endswith("." + d) for d in EXAMPLE_DOMAINS)


def term_kinds(text, terms):
    """Case-folded substring match, as in the repository guard."""
    folded = text.casefold()
    return ["private term #{}".format(n) for n, term in terms if term in folded]


def scan_line(text, terms):
    """Return finding kinds for one line, without the matched text."""
    kinds = term_kinds(text, terms)
    if HOME_PATH.search(text):
        kinds.append("hardcoded user home path")
    if any(not is_publishable_email(m.group(0)) for m in EMAIL.finditer(text)):
        kinds.append("email address outside the example domains")
    return kinds


def scan_lines(label, numbered_lines, terms):
    findings = []
    for line_number, text in numbered_lines:
        for kind in scan_line(text, terms):
            findings.append("{}:{}: {}".format(label, line_number, kind))
    return findings


def git(repo, *args):
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotePath=false"] + list(args),
            cwd=str(repo),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise PreflightError(
            "Could not run git in {}: {}".format(repo, error.strerror or error)
        )
    if result.returncode != 0:
        raise PreflightError(
            "git {} failed (exit status {}); no passing result is claimed.".format(
                args[0], result.returncode
            )
        )
    return result.stdout.decode("utf-8", errors="replace")


def list_commits(repo, rev_range):
    if rev_range.startswith("-"):
        raise PreflightError("The revision range must not start with '-'.")
    commits = git(repo, "rev-list", "--reverse", rev_range, "--").split()
    if not commits:
        raise PreflightError(
            "The range {} selected no commits; check the base.".format(rev_range)
        )
    return commits


def commit_metadata(repo, sha):
    fields = git(repo, "log", "-1", "--no-show-signature", "--format=%an%x00%ae%x00%cn%x00%ce%x00%P%x00%B", sha, "--")
    author, author_email, committer, committer_email, parents, message = fields.split(
        "\0", 5
    )
    return {
        "names": [author, committer],
        "emails": [("author", author_email), ("committer", committer_email)],
        "parents": parents.split(),
        "message": message.rstrip("\n"),
    }


def unquote_path(path):
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        raw = codecs.escape_decode(path[1:-1].encode("utf-8"))[0]
        return raw.decode("utf-8", errors="replace")
    return path


def commit_diff(repo, sha, parents):
    """Return ([(path, binary)], {path: [(new line number, added text)]})."""
    if parents:
        command = ["diff"] + GIT_DIFF_OPTIONS + [parents[0], sha, "--"]
    else:
        command = ["diff-tree", "-r", "--root", "--no-commit-id"] + GIT_DIFF_OPTIONS
        command += [sha, "--"]
    stats = git(repo, *command[:1], "--numstat", "-z", *command[1:])
    patch = git(repo, *command[:1], "-p", "-U0", *command[1:])

    changes, expected = [], {}
    for entry in stats.split("\0"):
        if not entry:
            continue
        additions, _, path = entry.split("\t", 2)
        binary = additions == "-"
        changes.append((path, binary))
        if not binary:
            expected[path] = int(additions)

    added = {}
    current, in_header, line_number = None, False, 0
    for line in patch.split("\n"):
        if line.startswith("diff --git "):
            current, in_header = None, True
        elif in_header and line.startswith("+++ "):
            target = unquote_path(line[4:].rstrip("\t"))
            current = target[2:] if target.startswith("b/") else None
        elif line.startswith("@@ "):
            in_header = False
            match = re.match(r"@@ -\S+ \+(\d+)", line)
            line_number = int(match.group(1)) if match else 0
        elif not in_header and current is not None and line.startswith("+"):
            added.setdefault(current, []).append((line_number, line[1:]))
            line_number += 1
    for path, count in expected.items():
        if len(added.get(path, [])) != count:
            raise PreflightError(
                "Could not read the added lines of commit {}; no passing result "
                "is claimed.".format(sha[:12])
            )
    return changes, added


def numbered(text):
    return list(enumerate(text.splitlines(), start=1))


class SecretCorpus:
    """Text blocks to scan for secrets, mapped back to their locations."""

    def __init__(self):
        self.entries = []

    def add(self, label, numbered_lines, source_name=""):
        if numbered_lines:
            suffix = _repository_guard.final_suffix(source_name)
            if suffix not in KEYWORD_SUFFIXES:
                suffix = ".txt"
            self.entries.append((label, numbered_lines, suffix))

    def scan(self):
        """Return findings; the scanner is required even for an empty corpus."""
        with tempfile.TemporaryDirectory(prefix="digits-preflight-") as directory:
            names = {}
            for index, (label, lines, suffix) in enumerate(self.entries):
                name = "{}{}".format(index, suffix)
                names[name] = (label, [number for number, _ in lines])
                with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
                    handle.write("".join(text + "\n" for _, text in lines))
            try:
                result = subprocess.run(
                    [SCANNER, "scan", "--no-verify", "--all-files"],
                    cwd=directory,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except FileNotFoundError:
                raise PreflightError(
                    "{} is missing; install it from requirements-dev.txt in an "
                    "isolated virtual environment, then rerun.".format(SCANNER)
                )
            except OSError:
                raise PreflightError(
                    "The secret scanner could not be started; no passing result "
                    "is claimed."
                )
        if result.returncode != 0:
            raise PreflightError(
                "The secret scanner failed (exit status {}); no passing result is "
                "claimed.".format(result.returncode)
            )
        try:
            results = json.loads(result.stdout)["results"]
            findings = []
            for name, entries in results.items():
                label, line_numbers = names[os.path.basename(name)]
                for entry in entries:
                    original = line_numbers[int(entry["line_number"]) - 1]
                    findings.append(
                        "{}:{}: secret ({})".format(label, original, entry["type"])
                    )
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            raise PreflightError(
                "The secret scanner produced unreadable output; no passing result "
                "is claimed."
            )
        return findings


def check_commit(repo, sha, terms, corpus):
    short = sha[:12]
    meta = commit_metadata(repo, sha)
    findings = []
    for role, address in meta["emails"]:
        if not is_github_noreply(address):
            findings.append(
                "commit {}: {} email is not a GitHub noreply address".format(short, role)
            )
    for role, name in zip(("author", "committer"), meta["names"]):
        for kind in scan_line(name, terms):
            findings.append("commit {}: {} name: {}".format(short, role, kind))
    for role, address in meta["emails"]:
        if is_github_noreply(address):
            continue  # its login is the public account being pushed as
        for kind in term_kinds(address, terms):
            findings.append("commit {}: {} email: {}".format(short, role, kind))

    label = "commit {} message".format(short)
    message_lines = numbered(meta["message"])
    for line_number, text in message_lines:
        if TRAILER.match(text) and any(
            not is_trailer_noreply(m.group(0)) for m in EMAIL.finditer(text)
        ):
            findings.append(
                "{}:{}: trailer email is not a noreply address".format(label, line_number)
            )
    findings.extend(scan_lines(label, message_lines, terms))
    corpus.add(label, message_lines)

    changes, added = commit_diff(repo, sha, meta["parents"])
    shown = {}
    for index, (path, binary) in enumerate(changes, start=1):
        kinds = scan_line(path, terms)
        shown[path] = path
        if kinds:
            # The path itself is sensitive: refer to it by position only.
            shown[path] = "changed path {}".format(index)
            for kind in kinds:
                findings.append("commit {}: changed path {}: {}".format(short, index, kind))
        if binary:
            findings.append(
                "commit {} {}: binary file not inspected".format(short, shown[path])
            )
    for path, lines in added.items():
        where = "commit {} {}".format(short, shown.get(path, path))
        findings.extend(scan_lines(where, lines, terms))
        corpus.add(where, lines, path.rsplit("/", 1)[-1])
    return findings


def read_text_source(source):
    if source == "-":
        stream = getattr(sys.stdin, "buffer", None)
        data = stream.read() if stream is not None else sys.stdin.read().encode()
        try:
            return data.decode("utf-8"), "stdin"
        except UnicodeDecodeError:
            raise PreflightError("stdin is not valid UTF-8.")
    try:
        return _repository_guard.read_text(Path(source)), source
    except UnicodeDecodeError:
        raise PreflightError("{} is not valid UTF-8.".format(source))
    except OSError as error:
        raise PreflightError(
            "Could not read {}: {}".format(source, error.strerror or "unreadable")
        )


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Check what a push or PR text would publish."
    )
    parser.add_argument(
        "--range",
        dest="ranges",
        action="append",
        default=[],
        metavar="RANGE",
        help="revision range to inspect, e.g. base..HEAD (repeatable)",
    )
    parser.add_argument(
        "--text",
        action="append",
        default=[],
        metavar="FILE",
        help="PR or issue text to scan; '-' reads standard input (repeatable)",
    )
    parser.add_argument(
        "--repo", help="repository to inspect (default: this checkout)"
    )
    args = parser.parse_args(argv)
    if not args.ranges and not args.text:
        parser.error("give --range, --text or both")
    return args


def main(argv=None):
    args = parse_args(argv)
    repo = Path(args.repo) if args.repo else ROOT

    try:
        terms_file = _repository_guard.resolve_terms_file()
        terms = _repository_guard.load_terms(terms_file) if terms_file else []
    except _repository_guard.TermsConfigurationError as error:
        print(error, file=sys.stderr)
        return 1
    if terms_file is None:
        print(
            "NOTE: no private-terms file ({} unset and ~/{} absent); private-term "
            "check skipped, other checks continue.".format(
                _repository_guard.PRIVATE_TERMS_ENV,
                _repository_guard.DEFAULT_PRIVATE_TERMS,
            ),
            file=sys.stderr,
        )

    findings = []
    corpus = SecretCorpus()
    commits = []
    try:
        for rev_range in args.ranges:
            for sha in list_commits(repo, rev_range):
                if sha not in commits:
                    commits.append(sha)
                    findings.extend(check_commit(repo, sha, terms, corpus))
        for source in args.text:
            text, label = read_text_source(source)
            lines = numbered(text)
            findings.extend(scan_lines(label, lines, terms))
            corpus.add(label, lines)
        findings.extend(corpus.scan())
    except PreflightError as error:
        print(error, file=sys.stderr)
        return 1

    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        print(
            "Publication preflight failed: {} finding(s).".format(len(findings)),
            file=sys.stderr,
        )
        return 1

    if terms_file is None:
        term_outcome = "private-term check skipped (no terms file)"
    else:
        term_outcome = "private-term check used {} terms".format(len(terms))
    scan_outcome = "secret scan covered {} non-empty blocks".format(len(corpus.entries))
    print(
        "Publication preflight passed ({} commits, {} texts); {}; {}.".format(
            len(commits), len(args.text), term_outcome, scan_outcome
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
