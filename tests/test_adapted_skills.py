"""Tests for the workflow-skill helpers and SKILL.md files (spec 40).

Helpers are loaded by file path; every GitHub call is faked in memory or by a
stub ``gh`` script inside a temporary directory.
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "plugin" / "skills"


def load_helper(skill, filename):
    path = SKILLS / skill / filename
    name = "digits_test_" + path.stem
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pr_status = load_helper("draft-pr-sweep", "pr_status.py")
shared_refs = load_helper("update-shared-workflows", "shared_refs.py")
reaction_plan = load_helper("review-reactions", "reaction_plan.py")

HEAD = "b" * 40
NOW = datetime(2025, 6, 2, 12, 0, 0, tzinfo=timezone.utc)
ME = "me"


def draft_pr(**overrides):
    pr = {
        "number": 7,
        "url": "https://github.com/o/r/pull/7",
        "title": "Draft work",
        "isDraft": True,
        "state": "OPEN",
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefName": "h",
        "headRefOid": HEAD,
        "body": "",
        "labels": {"nodes": []},
        "reviewRequests": {"nodes": []},
        "reviews": {"nodes": [{
            "state": "COMMENTED",
            "submittedAt": "2025-06-02T10:00:00Z",
            "commit": {"oid": HEAD},
            "author": {"login": "copilot-pull-request-reviewer"},
        }]},
        "reviewThreads": {"nodes": []},
        "commits": {"nodes": [{"commit": {
            "oid": HEAD,
            "messageHeadline": "work",
            "committedDate": "2025-06-02T09:00:00Z",
            "authoredDate": "2025-06-02T09:00:00Z",
            "parents": {"totalCount": 1},
            "statusCheckRollup": {"state": "SUCCESS"},
        }}]},
    }
    pr.update(overrides)
    return pr


def head_commit(pr):
    return pr["commits"]["nodes"][-1]["commit"]


def thread(author, reply_by=None, resolved=False, outdated=False, body="please fix"):
    comments = [{"body": body, "path": "a.py", "author": {"login": author}}]
    if reply_by is not None:
        comments.append({"body": "done", "path": "a.py", "author": {"login": reply_by}})
    return {"isResolved": resolved, "isOutdated": outdated, "comments": {"nodes": comments}}


def classify(pr):
    return pr_status.classify(pr, ME, NOW)


def bucket(pr):
    return classify(pr)["bucket"]


class DraftSweepClassificationTests(unittest.TestCase):
    def test_ready_by_default(self):
        record = classify(draft_pr())
        self.assertEqual(record["bucket"], "ready-candidate")
        self.assertTrue(record["automatedReviewOnHead"])
        self.assertEqual(record["automatedReviewAt"], "2025-06-02T10:00:00Z")
        self.assertEqual(record["minutesSinceHead"], 180)
        self.assertNotIn("repo", record)

    def test_precedence(self):
        self.assertEqual(
            bucket(draft_pr(labels={"nodes": [{"name": "Blocked"}]}, mergeable="CONFLICTING")),
            "skip-blocked-label")
        self.assertEqual(
            bucket(draft_pr(body="Depends on: o/r#3", mergeable="CONFLICTING")),
            "check-dependency")
        self.assertEqual(bucket(draft_pr(body="Depends on: none")), "ready-candidate")
        self.assertEqual(bucket(draft_pr(mergeable="CONFLICTING")), "rebase")
        requested = {"nodes": [{"requestedReviewer": {
            "__typename": "Bot", "login": "copilot-pull-request-reviewer"}}]}
        record = classify(draft_pr(reviewRequests=requested))
        self.assertEqual(record["bucket"], "review-in-flight")
        self.assertTrue(record["automatedReviewRequested"])
        self.assertEqual(record["humanReviewersRequested"], [])

    def test_my_last_reply_clears_a_thread(self):
        pr = draft_pr(reviewThreads={"nodes": [
            thread("copilot-pull-request-reviewer", reply_by=ME)]})
        record = classify(pr)
        self.assertEqual(record["bucket"], "ready-candidate")
        self.assertEqual(record["threadsAwaitingMe"], 0)
        self.assertEqual(len(record["openThreads"]), 1)

        record = classify(draft_pr(reviewThreads={"nodes": [thread("alice")]}))
        self.assertEqual(record["bucket"], "to-assess")
        self.assertEqual(record["humanThreadsAwaitingMe"], 1)
        self.assertEqual(record["openThreads"], [{
            "author": "alice", "automated": False, "body": "please fix",
            "lastAuthor": "alice", "path": "a.py"}])

    def test_authored_date_drives_staleness(self):
        pr = draft_pr()
        head_commit(pr)["committedDate"] = "2025-06-02T11:00:00Z"
        self.assertEqual(bucket(pr), "ready-candidate")

        pr = draft_pr()
        head_commit(pr)["committedDate"] = "2025-06-02T11:00:00Z"
        head_commit(pr)["authoredDate"] = "2025-06-02T11:00:00Z"
        record = classify(pr)
        self.assertEqual(record["bucket"], "check-stale-review")
        self.assertEqual(record["commitsAfterReview"], ["bbbbbbb work"])

        pr = draft_pr()
        head_commit(pr)["committedDate"] = "2025-06-02T11:55:00Z"
        record = classify(pr)
        self.assertEqual(record["bucket"], "check-active-elsewhere")
        self.assertEqual(record["minutesSinceHead"], 5)

    def test_ci_failure_and_missing_review(self):
        pr = draft_pr()
        head_commit(pr)["statusCheckRollup"] = {"state": "FAILURE"}
        self.assertEqual(bucket(pr), "fix-ci")
        record = classify(draft_pr(reviews={"nodes": []}))
        self.assertEqual(record["bucket"], "no-automated-review")
        self.assertIsNone(record["automatedReviewAt"])
        self.assertFalse(record["automatedReviewOnHead"])

    def test_dependency_hint_edge_cases(self):
        for body in ("Depends on nothing.", "depends on N/A"):
            record = classify(draft_pr(body=body))
            self.assertEqual(record["dependencyHints"], [], body)
            self.assertEqual(record["bucket"], "ready-candidate")
        record = classify(draft_pr(body="Depends on: nonexistent"))
        self.assertEqual(record["dependencyHints"], ["Depends on: nonexistent"])
        body = "depends on: #12\nstacked on #3\nblocked by z\nmust not merge\nbefore merge"
        self.assertEqual(
            classify(draft_pr(body=body))["dependencyHints"],
            ["depends on: #12", "stacked on #3", "blocked by z", "must not merge"])
        self.assertEqual(pr_status.dependency_hints("Depends on "), ["Depends on"])
        self.assertEqual(pr_status.dependency_hints(None), [])

    def test_blocking_labels_are_exact(self):
        for name in ("On Hold", "DO-NOT-MERGE", "do not merge", "blocked"):
            self.assertEqual(
                bucket(draft_pr(labels={"nodes": [{"name": name}]})),
                "skip-blocked-label", name)
        record = classify(draft_pr(labels={"nodes": [{"name": "blocked-by-infra"}]}))
        self.assertNotEqual(record["bucket"], "skip-blocked-label")
        self.assertEqual(record["labels"], ["blocked-by-infra"])

    def test_ci_states(self):
        for state, expected in (("ERROR", "fix-ci"), ("PENDING", "ci-pending"),
                                ("EXPECTED", "ci-pending")):
            pr = draft_pr()
            head_commit(pr)["statusCheckRollup"] = {"state": state}
            self.assertEqual(bucket(pr), expected, state)
        pr = draft_pr()
        head_commit(pr)["statusCheckRollup"] = None
        record = classify(pr)
        self.assertIsNone(record["ci"])
        self.assertEqual(record["bucket"], "ready-candidate")

    def test_merge_commits_do_not_make_review_stale(self):
        pr = draft_pr()
        pr["commits"]["nodes"].append({"commit": {
            "oid": "c" * 40, "messageHeadline": "Merge main",
            "committedDate": "2025-06-02T10:30:00Z",
            "authoredDate": "2025-06-02T10:30:00Z",
            "parents": {"totalCount": 2},
            "statusCheckRollup": {"state": "SUCCESS"}}})
        record = classify(pr)
        self.assertEqual(record["commitsAfterReview"], [])
        self.assertEqual(record["bucket"], "ready-candidate")

    def test_last_automated_review_selection(self):
        reviews = draft_pr()["reviews"]["nodes"] + [{
            "state": "COMMENTED", "submittedAt": "2025-06-02T11:00:00Z",
            "commit": {"oid": HEAD}, "author": {"login": "alice"}}]
        record = classify(draft_pr(reviews={"nodes": reviews}))
        self.assertEqual(record["automatedReviewAt"], "2025-06-02T10:00:00Z")

        reviews = copy.deepcopy(draft_pr()["reviews"]["nodes"])
        reviews[0]["commit"] = {"oid": "a" * 40}
        record = classify(draft_pr(reviews={"nodes": reviews}))
        self.assertFalse(record["automatedReviewOnHead"])

        reviews = [{"state": "COMMENTED", "submittedAt": "2025-06-02T10:00:00Z",
                    "commit": None, "author": None}]
        self.assertEqual(bucket(draft_pr(reviews={"nodes": reviews})), "no-automated-review")

    def test_human_reviewers_requested_in_order(self):
        requested = {"nodes": [
            {"requestedReviewer": {"__typename": "Team", "slug": "core"}},
            {"requestedReviewer": None},
            {"requestedReviewer": {"__typename": "User", "login": "bob"}},
        ]}
        record = classify(draft_pr(reviewRequests=requested))
        self.assertEqual(record["humanReviewersRequested"], ["core", "bob"])
        self.assertFalse(record["automatedReviewRequested"])
        self.assertNotEqual(record["bucket"], "review-in-flight")

    def test_bot_threads_and_thread_filters(self):
        record = classify(draft_pr(reviewThreads={"nodes": [thread("dependabot[bot]")]}))
        self.assertEqual(record["bucket"], "to-assess")
        self.assertEqual(record["threadsAwaitingMe"], 1)
        self.assertEqual(record["humanThreadsAwaitingMe"], 0)
        self.assertTrue(record["openThreads"][0]["automated"])

        record = classify(draft_pr(reviewThreads={"nodes": [
            thread("alice", resolved=True), thread("bob", outdated=True),
            {"isResolved": False, "isOutdated": False, "comments": {"nodes": []}}]}))
        self.assertEqual(record["openThreads"], [])
        self.assertEqual(record["bucket"], "ready-candidate")

        record = classify(draft_pr(reviewThreads={"nodes": [thread("alice", body="x" * 300)]}))
        self.assertEqual(record["openThreads"][0]["body"], "x" * 160)

    def test_empty_commit_list(self):
        record = classify(draft_pr(commits={"nodes": []}))
        self.assertEqual(record["minutesSinceHead"], 0)
        self.assertIsNone(record["ci"])
        self.assertEqual(record["bucket"], "check-active-elsewhere")

    def test_automated_login_rule(self):
        automated = pr_status.is_automated
        for login in ("Copilot", "my-copilot-thing", "renovate[bot]", "github-actions",
                      "github-advanced-security", "copilot-swe-agent"):
            self.assertTrue(automated(login), login)
        for login in ("", None, "alice", "renovate[BOT]", "GitHub-Actions"):
            self.assertFalse(automated(login), login)
        self.assertTrue(reaction_plan.is_automated("x[bot]"))
        self.assertFalse(reaction_plan.is_automated("alice"))


def graphql_answer(pr):
    return json.dumps({"data": {"repository": {"pullRequest": pr}}})


class FakeGh:
    """Records gh invocations and answers them from a handler function."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        return self.handler(args)

    def graphql_calls(self):
        return [c for c in self.calls if c[:2] == ["api", "graphql"]]


def graphql_target(args):
    values = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "-F")
    return values["owner"], values["name"], values["number"]


def run_pr_status(fake, argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(pr_status, "run_gh", fake), \
            mock.patch.object(pr_status, "sleep", lambda seconds: None), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = pr_status.main(argv)
    return code, out.getvalue(), err.getvalue()


class PrStatusCliTests(unittest.TestCase):
    def test_invalid_target_with_stub_gh_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "gh"
            stub.write_text(textwrap.dedent("""\
                #!/usr/bin/env bash
                if [ "$1" = api ] && [ "$2" = user ]; then echo me; exit 0; fi
                echo "unexpected gh call: $*" >&2
                exit 3
                """))
            stub.chmod(0o755)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ.get("PATH", ""), HOME=tmp)
            result = subprocess.run(
                [sys.executable, str(SKILLS / "draft-pr-sweep" / "pr_status.py"), "o/r#x"],
                capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("owner/repo#N", result.stderr)
        self.assertIn("o/r#x", result.stderr)

    def test_invalid_target_prints_no_records(self):
        fake = FakeGh(lambda args: "me\n" if args[:2] == ["api", "user"] else graphql_answer(draft_pr()))
        code, out, _ = run_pr_status(fake, ["o/r#1", "o/r#1x"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(fake.graphql_calls(), [])

    def test_error_record_for_failed_target(self):
        def handler(args):
            if args[:2] == ["api", "user"]:
                return "me\n"
            if graphql_target(args)[2] == "2":
                raise subprocess.CalledProcessError(1, ["gh"], stderr="boom")
            return graphql_answer(draft_pr())

        code, out, _ = run_pr_status(FakeGh(handler), ["o/r#1", "o/r#2"])
        self.assertEqual(code, 1)
        lines = out.splitlines()
        self.assertEqual(len(lines), 2)
        first, second = json.loads(lines[0]), json.loads(lines[1])
        self.assertEqual(first["repo"], "o/r")
        self.assertEqual(second["bucket"], "error")
        self.assertEqual(set(second), {"bucket", "error", "repo", "url"})
        self.assertEqual(second["url"], "https://github.com/o/r/pull/2")
        self.assertLessEqual(len(second["error"]), 300)
        for line in lines:
            self.assertEqual(line, json.dumps(json.loads(line), sort_keys=True))

    def test_null_pull_request_and_bad_json_are_errors(self):
        answers = iter([graphql_answer(None), "not json"])

        def handler(args):
            return "me\n" if args[:2] == ["api", "user"] else next(answers)

        code, out, _ = run_pr_status(FakeGh(handler), ["o/r#1", "o/r#2"])
        self.assertEqual(code, 1)
        self.assertEqual([json.loads(l)["bucket"] for l in out.splitlines()], ["error", "error"])

    def test_unknown_mergeable_refetches_once(self):
        def handler(args):
            if args[:2] == ["api", "user"]:
                return "me\n"
            return graphql_answer(draft_pr(mergeable="UNKNOWN"))

        fake = FakeGh(handler)
        code, out, _ = run_pr_status(fake, ["o/r#7"])
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.graphql_calls()), 2)
        self.assertEqual(json.loads(out)["mergeable"], "UNKNOWN")
        call = fake.graphql_calls()[0]
        self.assertIn("-f", call)
        self.assertEqual(graphql_target(call), ("o", "r", "7"))

    def test_search_targets_sorted_as_strings(self):
        def handler(args):
            if args[:2] == ["api", "user"]:
                return "me\n"
            if args[:2] == ["search", "prs"]:
                return json.dumps([
                    {"repository": {"nameWithOwner": "a/b"}, "number": 9},
                    {"repository": {"nameWithOwner": "a/b"}, "number": 10},
                ])
            owner, name, number = graphql_target(args)
            return graphql_answer(draft_pr(number=int(number)))

        fake = FakeGh(handler)
        code, out, _ = run_pr_status(fake, [])
        self.assertEqual(code, 0)
        search = [c for c in fake.calls if c[:2] == ["search", "prs"]][0]
        for flag in ("--draft", "--json", "--limit"):
            self.assertIn(flag, search)
        self.assertEqual([json.loads(l)["number"] for l in out.splitlines()], [10, 9])
        self.assertEqual([graphql_target(c)[2] for c in fake.graphql_calls()], ["10", "9"])
        self.assertTrue(all(json.loads(l)["repo"] == "a/b" for l in out.splitlines()))

    def test_login_failure_aborts_without_output(self):
        def handler(args):
            raise subprocess.CalledProcessError(4, ["gh"], stderr="not logged in")

        code, out, _ = run_pr_status(FakeGh(handler), ["o/r#1"])
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")

    def test_zero_targets_exit_zero(self):
        def handler(args):
            return "me\n" if args[:2] == ["api", "user"] else "[]"

        code, out, _ = run_pr_status(FakeGh(handler), [])
        self.assertEqual((code, out), (0, ""))


WORKFLOW_REPO = "example-org/github-workflows"
CI_YAML = textwrap.dedent("""\
    name: ci
    on: [push]
    jobs:
      x:
        uses: example-org/github-workflows/.github/workflows/x.yml@v1.2.1
      y:
        uses: 'example-org/github-workflows/.github/workflows/y.yml@v1.2.10'
      z:
        uses: example-org/github-workflows/.github/workflows/z.yml@main
      other:
        uses: other/repo/.github/workflows/x.yml@v1.2.1
    """)


class SharedRefsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ci = self.root / ".github" / "workflows" / "ci.yml"
        self.ci.parent.mkdir(parents=True)
        self.ci.write_text(CI_YAML)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_scan(self):
        refs = shared_refs.scan(str(self.root), [WORKFLOW_REPO])
        self.assertEqual(
            [(r["path"], r["ref"], r["semver"]) for r in refs],
            [(".github/workflows/x.yml", "v1.2.1", True),
             (".github/workflows/y.yml", "v1.2.10", True),
             (".github/workflows/z.yml", "main", False)])
        self.assertEqual(list(refs[0]), ["file", "line", "repo", "path", "ref", "semver"])
        self.assertEqual(refs[0]["file"], ".github/workflows/ci.yml")
        self.assertEqual([r["line"] for r in refs], [5, 7, 9])
        self.assertTrue(all(r["repo"] == WORKFLOW_REPO for r in refs))

    def test_dry_run_and_exact_tag(self):
        before = self.ci.read_bytes()
        changes = shared_refs.update(str(self.root), WORKFLOW_REPO, "v1.2.1", "v1.3.0")
        self.assertEqual(changes, [{"file": ".github/workflows/ci.yml", "references": 1}])
        self.assertEqual(self.ci.read_bytes(), before)

        shared_refs.update(str(self.root), WORKFLOW_REPO, "v1.2.1", "v1.3.0", write=True)
        text = self.ci.read_text()
        self.assertIn("x.yml@v1.3.0", text)
        self.assertIn("y.yml@v1.2.10", text)
        self.assertIn("other/repo/.github/workflows/x.yml@v1.2.1", text)

    def test_unsafe_versions_refused(self):
        before = self.ci.read_bytes()
        for old, new in (("v1.2.1", "v2.0.0"), ("v1.2.1", "v1.2.0"),
                         ("main", "v1.3.0"), ("v1.2.1", "v1.2.1"), ("v1.2.1", "v1.3")):
            with self.assertRaises(ValueError, msg=(old, new)):
                shared_refs.update(str(self.root), WORKFLOW_REPO, old, new, write=True)
        self.assertEqual(self.ci.read_bytes(), before)
        changes = shared_refs.update(str(self.root), WORKFLOW_REPO, "v1.2.1", "v2.0.0",
                                     allow_major=True)
        self.assertTrue(changes)

    def test_semver_parsing(self):
        self.assertEqual(shared_refs.parse_semver("v1.2.3"), (1, 2, 3))
        self.assertEqual(shared_refs.parse_semver("1.10.0"), (1, 10, 0))
        for tag in ("v1.2.3-rc1", "v1.2", "V1.2.3", "main", "a" * 40, "v1.2.3 "):
            self.assertIsNone(shared_refs.parse_semver(tag), tag)

    def test_examined_files(self):
        self.write(".github/actions/build/action.yaml",
                   "runs:\n  steps:\n    - uses: example-org/github-workflows/actions/a@v1.2.1\n")
        self.write(".github/actions/action.yml",
                   "runs:\n  steps:\n    - uses: \"example-org/github-workflows@v1.2.1\"\n")
        self.write(".github/actions/a-b/action.yml", "x: 1\n")
        self.write(".github/workflows/sub/x.yml",
                   "jobs:\n  a:\n    uses: example-org/github-workflows/x.yml@v1.2.1\n")
        self.write(".github/workflows/notes.txt",
                   "uses: example-org/github-workflows/x.yml@v1.2.1\n")
        outside = self.write("elsewhere/linked.yml",
                             "uses: example-org/github-workflows/l.yml@v1.2.1\n")
        os.symlink(str(outside), str(self.root / ".github" / "workflows" / "linked.yml"))

        files = [p.relative_to(self.root).as_posix()
                 for p in shared_refs.examined_files(str(self.root))]
        self.assertEqual(files, [
            ".github/actions/a-b/action.yml",
            ".github/actions/action.yml",
            ".github/actions/build/action.yaml",
            ".github/workflows/ci.yml",
        ])
        refs = shared_refs.scan(str(self.root), [WORKFLOW_REPO])
        self.assertEqual(refs[0]["file"], ".github/actions/action.yml")
        self.assertEqual(refs[0]["path"], "")
        self.assertEqual(refs[1]["file"], ".github/actions/build/action.yaml")
        self.assertEqual(refs[1]["path"], "actions/a")
        self.assertNotIn(".github/workflows/linked.yml", [r["file"] for r in refs])

    def test_component_sort_order(self):
        self.write(".github/actions/a-b/action.yml", "x: 1\n")
        self.write(".github/actions/a/action.yml", "x: 1\n")
        files = [p.relative_to(self.root).as_posix()
                 for p in shared_refs.examined_files(str(self.root))]
        self.assertLess(files.index(".github/actions/a/action.yml"),
                        files.index(".github/actions/a-b/action.yml"))

    def test_missing_github_dir(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(shared_refs.scan(empty, [WORKFLOW_REPO]), [])

    def test_scan_prefix_rules(self):
        self.ci.write_text(
            "a: uses: o/r@x\n"
            "b: uses: other/o/r@x\n"
            "c: uses: o/r2@x\n"
            "d: uses:o/r/p@y uses: \"o/r@z\" # note\n")
        refs = shared_refs.scan(str(self.root), ["o/r"])
        self.assertEqual([(r["line"], r["path"], r["ref"]) for r in refs],
                         [(1, "", "x"), (4, "p", "y"), (4, "", "z")])

    def test_update_terminators(self):
        self.ci.write_text(
            "  uses: example-org/github-workflows/.github/workflows/x.yml@v1.2.1 # pin\n"
            "  uses: example-org/github-workflows/.github/workflows/y.yml@v1.2.1,\n"
            "  uses: example-org/github-workflows/.github/workflows/z.yml@v1.2.1-rc\n"
            "  uses: example-org/github-workflows/.github/workflows/w.yml@v1.2.1")
        changes = shared_refs.update(str(self.root), WORKFLOW_REPO, "v1.2.1", "v1.2.2", write=True)
        self.assertEqual(changes, [{"file": ".github/workflows/ci.yml", "references": 2}])
        text = self.ci.read_text()
        self.assertIn("x.yml@v1.2.2 # pin", text)
        self.assertIn("y.yml@v1.2.1,", text)
        self.assertIn("z.yml@v1.2.1-rc", text)
        self.assertIn("w.yml@v1.2.2", text)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = shared_refs.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_cli_exit_codes(self):
        root = str(self.root)
        self.assertEqual(self.run_cli("scan", "--root", root)[:2], (1, ""))
        self.assertEqual(self.run_cli("latest")[:2], (1, ""))
        code, out, err = self.run_cli("scan", "--root", root, "--repo", "bad")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("bad", err)
        self.assertEqual(self.run_cli("update", "--repo", "bad", "--from", "v1.2.1",
                                      "--to", "v1.3.0", "--root", root)[:2], (1, ""))
        self.assertEqual(self.run_cli()[:2], (2, ""))
        self.assertEqual(self.run_cli("scan", "--bogus")[:2], (2, ""))
        self.assertEqual(self.run_cli("update", "--repo", WORKFLOW_REPO, "--from", "v1.2.1")[:2],
                         (2, ""))
        code, out, _ = self.run_cli("update", "--root", root, "--repo", WORKFLOW_REPO,
                                    "--from", "v1.2.1", "--to", "v1.2.1", "--write")
        self.assertEqual((code, out), (2, ""))

    def test_cli_update_and_scan_output(self):
        root = str(self.root)
        code, out, _ = self.run_cli("update", "--root", root, "--repo", WORKFLOW_REPO,
                                    "--from", "1.2.1", "--to", "1.3.0", "--write")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"write": True, "changes": []})
        self.assertIn("x.yml@v1.2.1", self.ci.read_text())

        code, out, _ = self.run_cli("update", "--root", root, "--repo", WORKFLOW_REPO,
                                    "--from", "v1.2.1", "--to", "v1.3.0")
        self.assertEqual(code, 0)
        self.assertEqual(out, json.dumps({"write": False, "changes": [
            {"file": ".github/workflows/ci.yml", "references": 1}]}, indent=2) + "\n")
        self.assertIn("x.yml@v1.2.1", self.ci.read_text())

        code, out, _ = self.run_cli("scan", "--root", root, "--repo", WORKFLOW_REPO,
                                    "--repo", WORKFLOW_REPO)
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)), 6)

    def test_latest(self):
        answers = {
            "repos/a/b/tags": "v1.10.0\nv1.9.0\nmain\n1.10.0\nv2.0.0-rc1\n",
            "repos/c/d/tags": "main\ndevelop\n",
        }
        calls = []

        def fake(args):
            calls.append(args)
            self.assertEqual(args[:2], ["api", "--paginate"])
            return answers[args[2]]

        with mock.patch.object(shared_refs, "run_gh", fake):
            code, out, _ = self.run_cli("latest", "--repo", "a/b", "--repo", "c/d",
                                        "--repo", "a/b")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"a/b": "v1.10.0", "c/d": None})
        self.assertEqual(list(json.loads(out)), ["a/b", "c/d"])
        self.assertEqual(shared_refs.newest_tag(["1.2.3", "v1.2.3"]), "v1.2.3")

        def failing(args):
            raise subprocess.CalledProcessError(1, ["gh"])

        with mock.patch.object(shared_refs, "run_gh", failing):
            code, out, _ = self.run_cli("latest", "--repo", "a/b")
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")


PR_A = "https://github.com/o/r/pull/1"
PR_B = "https://github.com/o/r/pull/2"
CUTOFF = 100.0


def status(state="OPEN", decision="REVIEW_REQUIRED", reviews=(), author="me"):
    return {"state": state, "reviewDecision": decision, "author": author,
            "reviews": [{"state": s, "login": login} for login, s in reviews]}


def message(ts="200.0", user="U1", links=(PR_A, PR_B), reactions=({"name": "speech_balloon"},)):
    text = "review request for " + " and ".join("<%s|%s>" % (u, u.rsplit("/", 1)[1]) for u in links)
    return {"ts": ts, "user": user, "text": text, "reactions": list(reactions)}


def fetcher(statuses):
    def fetch(url):
        return statuses[url]
    return fetch


def plan(messages, statuses, **kwargs):
    return reaction_plan.plan(messages, "U1", CUTOFF, fetch=fetcher(statuses), **kwargs)


class ReactionPlanTests(unittest.TestCase):
    def test_all_linked_prs_must_qualify(self):
        result = plan([message()], {
            PR_A: status("MERGED", "APPROVED"), PR_B: status("OPEN", "APPROVED")})
        self.assertEqual(result["rows"][0]["reactions"], ["white_check_mark"])
        self.assertEqual(result["rows"][0]["status"], "Approved")

        result = plan([message()], {
            PR_A: status("MERGED", "APPROVED"), PR_B: status("MERGED", "APPROVED")})
        self.assertEqual([c["emoji"] for c in result["calls"]],
                         ["white_check_mark", "twisted_rightwards_arrows"])
        self.assertEqual(result["calls"][0]["ts"], "200.0")
        row = result["rows"][0]
        self.assertEqual(list(row), ["ts", "prs", "status", "reactions", "missing", "action"])
        self.assertEqual((row["status"], row["action"]), ("Merged", "Pending"))

    def test_only_outside_humans_count_and_aliases_present(self):
        reviews = (("copilot-pull-request-reviewer", "COMMENTED"), ("me", "COMMENTED"),
                   ("x[bot]", "CHANGES_REQUESTED"))
        result = plan([message()], {PR_A: status(reviews=reviews), PR_B: status(reviews=reviews)})
        self.assertEqual(result["rows"][0]["reactions"], [])

        result = plan([message()], {
            PR_A: status(reviews=(("alice", "CHANGES_REQUESTED"),)), PR_B: status()})
        row = result["rows"][0]
        self.assertEqual(row["action"], "Already present")
        self.assertEqual(row["status"], "Has feedback")
        self.assertEqual(result["calls"], [])

    def test_approved_and_dismissed_reviews_are_not_feedback(self):
        reviews = (("alice", "APPROVED"), ("bob", "DISMISSED"), ("carol", "PENDING"))
        result = plan([message(links=(PR_A,))], {PR_A: status(reviews=reviews)})
        self.assertEqual(result["rows"][0]["reactions"], [])
        result = plan([message(links=(PR_A,), reactions=())],
                      {PR_A: status(reviews=((None, "COMMENTED"),))})
        self.assertEqual(result["rows"][0]["reactions"], ["speech_balloon"])

    def test_configured_names_and_aliases(self):
        msg = message(links=(PR_A,), reactions=("merge",))
        result = plan([msg], {PR_A: status("MERGED", "APPROVED", (("alice", "COMMENTED"),))},
                      reactions={"feedback": ("eyes",), "approved": ("ok",)})
        self.assertEqual(result["rows"][0]["reactions"],
                         ["eyes", "ok", "twisted_rightwards_arrows"])
        self.assertEqual([c["emoji"] for c in result["calls"]], ["eyes", "ok"])

    def test_filtering_and_errors(self):
        messages = [message("200.0", "U2", (PR_A,)), message("50.0", "U1", (PR_A,)),
                    message("300.0", "U1", (PR_B,))]

        def failing(url):
            raise ValueError("cannot parse")

        result = reaction_plan.plan(messages, "U1", CUTOFF, fetch=failing)
        self.assertEqual([(r["ts"], r["status"]) for r in result["rows"]], [("300.0", "Error")])
        self.assertEqual(result["calls"], [])
        row = result["rows"][0]
        self.assertEqual(list(row), ["ts", "prs", "status", "reactions", "action", "errors"])
        self.assertEqual(row["action"], "Skipped (PR read failed)")
        self.assertEqual(row["errors"], [PR_B + ": cannot parse"])

    def test_every_link_attempted_after_failure(self):
        seen = []

        def fetch(url):
            seen.append(url)
            if url == PR_A:
                raise subprocess.TimeoutExpired(["gh"], 30)
            return status()

        result = reaction_plan.plan([message()], "U1", CUTOFF, fetch=fetch)
        self.assertEqual(seen, [PR_A, PR_B])
        self.assertEqual(result["rows"][0]["status"], "Error")
        self.assertEqual(len(result["rows"][0]["errors"]), 1)

    def test_reaction_name_and_link_normalization(self):
        msg = {"ts": "200.0", "user": "U1", "reactions": [
                   {"name": "white_check_mark::skin-tone-2"}, {"count": 1}, "thumbsup::skin-tone-3"],
               "text": "see <%s/files|#1> and %s and %s> and http://github.com/o/r/pull/9 "
                       "and https://example.com/o/r/pull/8" % (PR_A, PR_A, PR_A)}
        self.assertEqual(reaction_plan.reaction_names(msg),
                         ["white_check_mark", "", "thumbsup"])
        result = plan([msg], {PR_A: status(decision="APPROVED")})
        row = result["rows"][0]
        self.assertEqual(row["prs"], [PR_A])
        self.assertEqual(row["action"], "Already present")

    def test_ordering_and_status_labels(self):
        messages = [message("150", links=(PR_A,)), message(250.5, links=(PR_B,)),
                    {"user": "U1", "text": PR_A}]
        result = plan(messages, {PR_A: status(), PR_B: status()})
        self.assertEqual([r["ts"] for r in result["rows"]], [250.5, "150"])
        row = result["rows"][1]
        self.assertEqual((row["action"], row["status"]), ("No reaction needed", "Awaiting review"))

        result = plan([message()], {PR_A: status("MERGED"), PR_B: status("CLOSED")})
        self.assertEqual(result["rows"][0]["status"], "Closed (check)")
        result = plan([message()], {PR_A: status("MERGED"), PR_B: status("OPEN")})
        self.assertEqual(result["rows"][0]["status"], "Partly merged")
        self.assertEqual(plan([message(links=())], {})["rows"], [])

    def test_author_login_override(self):
        statuses = {PR_A: status(reviews=(("bob", "COMMENTED"),), author="alice")}
        msg = message(links=(PR_A,), reactions=())
        self.assertEqual(plan([msg], statuses)["rows"][0]["reactions"], ["speech_balloon"])
        self.assertEqual(plan([msg], statuses, author_login="bob")["rows"][0]["reactions"], [])
        statuses = {PR_A: status(reviews=(("alice", "COMMENTED"),), author="alice")}
        self.assertEqual(plan([msg], statuses)["rows"][0]["reactions"], [])

    def test_emoji_list_parsing(self):
        self.assertEqual(reaction_plan.parse_emoji_list(" :eyes: ,ok"), ("eyes", "ok"))
        self.assertEqual(reaction_plan.parse_emoji_list("+1,a_b-c'd"), ("+1", "a_b-c'd"))
        for bad in ("Eyes", "::", "", " , ", "a b"):
            with self.assertRaises(ValueError, msg=bad):
                reaction_plan.parse_emoji_list(bad)


class ReactionPlanCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def messages_file(self, data):
        path = self.dir / "messages.json"
        path.write_text(json.dumps(data))
        return str(path)

    def run_main(self, argv, statuses=None):
        out, err = io.StringIO(), io.StringIO()
        fetch = fetcher(statuses or {})
        with mock.patch.object(reaction_plan, "fetch_pr_status", fetch), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = reaction_plan.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_usage_errors(self):
        path = self.messages_file([])
        code, out, err = self.run_main([path, "--user-id", "C123"])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("user ID", err)
        self.assertEqual(self.run_main([path, "--user-id", "U1", "--feedback", "Eyes"])[:2],
                         (2, ""))
        self.assertEqual(self.run_main([path])[:2], (2, ""))

    def test_subprocess_usage_error(self):
        path = self.messages_file([])
        result = subprocess.run(
            [sys.executable, str(SKILLS / "review-reactions" / "reaction_plan.py"), path,
             "--user-id", "D123"],
            capture_output=True, text=True, timeout=60,
            env=dict(os.environ, HOME=str(self.dir)))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_feedback_override_with_alias_and_wrapper(self):
        msg = message(links=(PR_A,), reactions=({"name": "look"},))
        path = self.messages_file({"messages": [msg]})
        statuses = {PR_A: status(reviews=(("alice", "COMMENTED"),))}
        code, out, _ = self.run_main(
            [path, "--user-id", "U1", "--now", "300", "--feedback", " :eyes: ,look"], statuses)
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result["rows"][0]["reactions"], ["eyes"])
        self.assertEqual(result["rows"][0]["action"], "Already present")
        self.assertEqual(out, json.dumps(result, indent=2) + "\n")

        code, out, _ = self.run_main(
            [path, "--user-id", "U1", "--now", "300", "--feedback", "eyes"], statuses)
        self.assertEqual(json.loads(out)["calls"], [{"ts": "200.0", "emoji": "eyes"}])

        path = self.messages_file({"other": []})
        code, out, _ = self.run_main([path, "--user-id", "U1"])
        self.assertEqual((code, json.loads(out)), (0, {"rows": [], "calls": []}))

    def test_window_uses_clock_and_seconds(self):
        now = time.time()
        recent = message(ts="%.6f" % (now - 60), links=(PR_A,))
        old = message(ts="%.6f" % (now - 7200), links=(PR_B,))
        path = self.messages_file([recent, old])
        statuses = {PR_A: status(), PR_B: status()}
        code, out, _ = self.run_main([path, "--user-id", "U1", "--seconds", "3600"], statuses)
        self.assertEqual(code, 0)
        self.assertEqual([r["prs"] for r in json.loads(out)["rows"]], [[PR_A]])

        code, out, _ = self.run_main(
            [path, "--user-id", "U1", "--seconds", "3600", "--now", "0"], statuses)
        self.assertEqual([r["prs"] for r in json.loads(out)["rows"]], [[PR_A]])

        future = message(ts="%.6f" % (now + 3600), links=(PR_B,))
        path = self.messages_file([recent, future])
        code, out, _ = self.run_main([path, "--user-id", "U1", "--seconds", "0"], statuses)
        self.assertEqual([r["prs"] for r in json.loads(out)["rows"]], [[PR_B]])

        path = self.messages_file([message(ts="1000", links=(PR_A,)),
                                   message(ts="999.5", links=(PR_B,))])
        code, out, _ = self.run_main(
            [path, "--user-id", "U1", "--seconds", "0", "--now", "1000"], statuses)
        self.assertEqual([r["prs"] for r in json.loads(out)["rows"]], [[PR_A]])


WORKFLOW_SKILLS = (
    "review-reactions", "rebase-pr", "investigate", "draft-pr-sweep",
    "challenge-pass", "update-shared-workflows", "assess-and-address",
)

REQUIRED_PHRASES = {
    "rebase-pr": ["--force-with-lease=refs/heads/<head>:<old-sha>"],
    "review-reactions": ["Do not hardcode", "only after approval"],
    "update-shared-workflows": ["never commits or pushes"],
    "draft-pr-sweep": ["re-read the PR head", "read-only"],
    "assess-and-address": ["three rounds", "never reply, resolve"],
    "request-review": ["never enable auto-merge", "Only after explicit approval"],
}


def skill_text(name):
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


class SkillFileTests(unittest.TestCase):
    def test_frontmatter_and_size(self):
        for name in WORKFLOW_SKILLS:
            with self.subTest(skill=name):
                lines = skill_text(name).splitlines()
                self.assertLessEqual(len(lines), 190)
                self.assertEqual(lines[0], "---")
                self.assertEqual(lines[1], "name: " + name)
                self.assertTrue(lines[2].startswith("description: "))
                self.assertTrue(lines[2][len("description: "):].strip())
                self.assertFalse(lines[2][len("description: ")].isspace())
                self.assertEqual(lines[3], "user-invocable: true")
                self.assertEqual(lines[4], "---")
                body = [line for line in lines[5:] if line.strip()]
                self.assertTrue(body[0].startswith("# "))
                self.assertTrue(body[1].startswith("Usage: `/digits:" + name))

    def test_references_exist(self):
        for relative in ("investigate/references/artifact-shapes.md",
                         "challenge-pass/references/challenger-prompt.md"):
            text = (SKILLS / relative).read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# "), relative)
        prompt = (SKILLS / "challenge-pass/references/challenger-prompt.md").read_text()
        for word in ("holds", "changed", "unverified", "Not checked", "--repo"):
            self.assertIn(word, prompt)

    def test_every_skill_name_matches_directory(self):
        skill_files = sorted(SKILLS.glob("*/SKILL.md"))
        self.assertEqual(len(skill_files), 14, [p.parent.name for p in skill_files])
        for path in skill_files:
            name = path.parent.name
            with self.subTest(skill=name):
                lines = path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(lines[0], "---")
                end = lines.index("---", 1)
                block = lines[1:end]
                self.assertIn("name: " + name, block)
                descriptions = [l for l in block if l.startswith("description:")]
                self.assertEqual(len(descriptions), 1)
                value = descriptions[0][len("description:"):]
                if value.startswith(" "):
                    value = value[1:]
                self.assertTrue(value and not value[0].isspace(), descriptions[0])

    def test_write_gates_stay_documented(self):
        for name, phrases in REQUIRED_PHRASES.items():
            text = skill_text(name)
            for phrase in phrases:
                with self.subTest(skill=name, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_helpers_are_executable_scripts(self):
        for relative in ("draft-pr-sweep/pr_status.py",
                         "update-shared-workflows/shared_refs.py",
                         "review-reactions/reaction_plan.py"):
            path = SKILLS / relative
            with self.subTest(helper=relative):
                self.assertTrue(path.read_text().startswith("#!/usr/bin/env python3\n"))
                self.assertTrue(os.access(str(path), os.X_OK))
                self.assertIn('python3 "<skill-dir>/%s"' % path.name,
                              skill_text(path.parent.name))


BATCHED_ASK_SKILLS = (
    "assess-and-address", "draft-pr-sweep", "investigate", "request-review",
    "review-reactions", "self-improve", "standup-update", "update-shared-workflows",
)
BATCHED_ASK_POINTER = (
    "(the Digits bootstrap's Communication rule: one `ask_user` or "
    "`AskUserQuestion` call, or one numbered list when the decisions do not fit)"
)


class HostNeutralAskTests(unittest.TestCase):
    """Skills ask through the bootstrap's batched-ask rule, not one host's tool."""

    def test_skills_point_at_the_shared_rule(self):
        for name in BATCHED_ASK_SKILLS:
            with self.subTest(skill=name):
                text = " ".join(skill_text(name).split())
                self.assertIn("batched ask", text)
                self.assertEqual(text.count(BATCHED_ASK_POINTER), 1)
                self.assertEqual(text.count("`ask_user`"), 1, "ask_user only in the pointer")

    def test_no_other_skill_names_a_single_host_tool(self):
        for path in sorted(SKILLS.glob("*/SKILL.md")):
            name = path.parent.name
            if name in BATCHED_ASK_SKILLS or name == "inter-env":
                continue
            with self.subTest(skill=name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("ask_user", text)
                self.assertNotIn("AskUserQuestion", text)

    def test_bootstrap_defines_the_rule(self):
        text = " ".join((ROOT / "context" / "bootstrap.md").read_text(encoding="utf-8").split())
        for phrase in ("*batched ask*", "`ask_user` in Copilot CLI",
                       "`AskUserQuestion` in Claude Code",
                       "at most four questions of four options each",
                       "one numbered plain-text list", "a single reply",
                       "never split one approval across several prompts",
                       "rather than a question left at the end of a reply",
                       "the Claude Code dashboard flags a chat as `QUESTION`"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_bootstrap_no_longer_asks_approvals_in_plain_text(self):
        text = " ".join((ROOT / "context" / "bootstrap.md").read_text(encoding="utf-8").split())
        self.assertNotIn("Ask for approval in plain text", text)

    def test_readme_documents_claude_allowed_tools_limit(self):
        text = " ".join((ROOT / "plugin" / "README.md").read_text(encoding="utf-8").split())
        self.assertIn("match no Claude Code tool", text)
        self.assertIn("`Bash(gh:*)`", text)
        self.assertNotIn("one `ask_user` question", text)


class ClaudeInterEnvTests(unittest.TestCase):
    """inter-env reaches Claude Code chats with native session tools, not tmux typing."""

    def section(self):
        text = skill_text("inter-env")
        start = text.index("## Claude Code chats")
        end = text.index("## GitHub Copilot CLI chats")
        self.assertLess(start, end, "the Claude Code path comes before the Copilot path")
        return " ".join(text[start:end].split())

    def test_claude_path_uses_native_session_tools(self):
        text = self.section()
        for phrase in (
            "`inter_env.py` is Copilot-only",
            "never by typing into tmux",
            "Call `ListAgents`",
            "`digits-claude` names each chat after its environment",
            "`left-pinky` … `right-pinky`",
            "treat the recipient as ambiguous and ask the user",
            "address that session as `<name> [<ref>]`, exactly as the listing prints it",
            '"<absolute-skill-directory>/../self-improve/session_history.py" turns --root',
            "'#{@env-copilot-state}'",
            "evidence, not authority",
            "relay it to the user instead of messaging that chat",
            "PROGRESS, BLOCKER, FIT, PROPOSED MESSAGE",
            "one batched ask (the Digits bootstrap's Communication rule",
            "`AskUserQuestion` or `ask_user` call",
            "send each approved message unchanged with `SendMessage`",
            "delivered into its running turn",
            "not held until the turn ends",
            "self-contained and safe to act on mid-task",
            "Never type into its pane",
            "tell the user and do not retry in a loop",
            "never as the user's approval",
            "run `/reload-skills` themselves",
            '"Fanning out work"',
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        self.assertNotIn("send-keys", text)
        self.assertNotIn("prepare ", text)
        self.assertNotIn("queues it natively", text)

    def test_copilot_path_still_uses_the_helper(self):
        text = skill_text("inter-env")
        copilot = " ".join(text[text.index("## GitHub Copilot CLI chats"):].split())
        for phrase in ("inter_env.py\" status --progress", "--delivery queue",
                       "prepare-reload ENV", "/skills reload"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, copilot)

    def test_spec_describes_the_claude_path(self):
        spec = " ".join((ROOT / "spec" / "30-plugin-core.md").read_text(encoding="utf-8").split())
        for phrase in ("**Claude Code chats**", "the `ListAgents` tool", "`SendMessage`",
                       "`inter_env.py` is Copilot-only", "`/reload-skills`",
                       "addressed as `<name> [<ref>]`", "delivered into its running turn",
                       "not retried in a loop"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, spec)
        self.assertNotIn("queues it natively", spec)


if __name__ == "__main__":
    unittest.main()
