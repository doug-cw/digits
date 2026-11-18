"""Tests for plugin/skills/token-usage/token_usage.py on invented transcripts."""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "plugin" / "skills" / "token-usage" / "token_usage.py"

spec = importlib.util.spec_from_file_location("digits_token_usage_under_test", HELPER)
usage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usage)

ENV_A = "/srv/envs/left_pinky"
ENV_B = "/srv/envs/right_ring"
RATES = {
    "source": "https://example.invalid/pricing", "retrieved": "2026-01-01",
    "web_search_per_request": 0.01,
    "models": {
        "claude-test-big": {"input": 4, "cache_write_5m": 5, "cache_write_1h": 8, "cache_read": 0.2,
                            "output": 20, "fast": {"input": 8, "output": 40}, "geo_multipliers": {"us": 1.1}},
        "claude-test-small": {"input": 0.1, "cache_write_5m": 0.125, "cache_write_1h": 0.2, "cache_read": 0.01,
                              "output": 0.5, "tiers": [{"prompt_tokens_over": 100000, "input": 0.5,
                                                        "cache_write_5m": 0.625, "cache_write_1h": 1,
                                                        "cache_read": 0.05, "output": 2.5}]},
    },
}


def reply(stamp, cwd, msg_id, model="claude-test-big", branch="main", **counts):
    body = {"input_tokens": counts.get("i", 0), "output_tokens": counts.get("o", 0),
            "cache_creation_input_tokens": counts.get("w5", 0) + counts.get("w1", 0),
            "cache_read_input_tokens": counts.get("r", 0),
            "cache_creation": {"ephemeral_5m_input_tokens": counts.get("w5", 0),
                               "ephemeral_1h_input_tokens": counts.get("w1", 0)}}
    for key in ("speed", "inference_geo"):
        if key in counts:
            body[key] = counts[key]
    return {"type": "assistant", "timestamp": stamp, "cwd": cwd, "gitBranch": branch,
            "requestId": "req_" + msg_id,
            "message": {"id": msg_id, "model": model, "usage": body, "content": [{"type": "text", "text": "x"}]}}


class TokenUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.projects = base / "projects"
        self.projects.mkdir()
        self.rates = base / "rates.json"
        self.rates.write_text(json.dumps(RATES))
        a = ENV_A
        big = reply("2026-03-02T09:00:05Z", a, "m1", i=1_000_000, o=1_000_000)
        self.write(a, "aaaa0001", [
            {"type": "custom-title", "customTitle": "Fix widget parser"},
            {"type": "user", "timestamp": "2026-03-02T09:00:00Z", "cwd": a, "message": {"content": "hi"}},
            big, big,  # the same request repeated for a second content block
            reply("2026-03-02T09:01:00Z", a + "/repo", "m2", branch="feat/x", w1=1_000_000, r=1_000_000),
            reply("2026-03-02T09:02:00Z", a, "m3", model="<synthetic>"),
        ])
        self.write(a, "aaaa0001/subagents/agent-1", [
            reply("2026-03-02T09:03:00Z", a, "m4", model="claude-test-small", o=1_000_000),
        ])
        self.write(ENV_B, "bbbb0002", [
            reply("2026-03-05T10:00:00Z", ENV_B, "m5", model="anthropic.claude-test-big-20260101[1m]",
                  o=1_000_000, speed="fast", inference_geo="us"),
            reply("2026-03-05T10:01:00Z", ENV_B, "m6", model="claude-unknown", o=5),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, cwd, name, records):
        path = self.projects / usage.history.slug(cwd) / (name + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in records) + "not json\n")

    def run_cli(self, *args, ok=True):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--projects-dir", str(self.projects), "report", "--rates", str(self.rates)]
        argv += ["--projects", str(self.write_rules([]))] if "--projects" not in args else []
        with redirect_stdout(out), redirect_stderr(err):
            code = usage.main(argv + list(args))
        self.assertEqual(code == 0, ok, err.getvalue())
        return out.getvalue() if code == 0 else err.getvalue()

    def report(self, *args):
        return json.loads(self.run_cli(*args))

    def test_model_key_normalizes_ids(self):
        self.assertEqual(usage.model_key("us.anthropic.claude-opus-4-20250514[1m]"), "claude-opus-4")
        self.assertEqual(usage.model_key("claude-opus-5-5"), "claude-opus-5-5")
        self.assertEqual(usage.model_key("claude-opus-4-1@20250805"), "claude-opus-4-1")

    def test_task_totals_dedupe_and_include_subagents(self):
        result = self.report("--projects", str(self.write_rules([])), "--until", "2026-03-02")
        self.assertEqual(result["total"], 1)
        task = result["items"][0]
        self.assertEqual((task["task"], task["title"], task["requests"]), ("aaaa0001", "Fix widget parser", 3))
        # m1: 4 + 20; m2: 8 + 0.2; m4 (sub-agent, small model): 0.5
        self.assertAlmostEqual(task["cost_usd"], 32.7)
        self.assertEqual(task["output"], 2_000_000)
        self.assertEqual(task["cache_write_1h"], 1_000_000)

    def test_fast_geo_and_unpriced(self):
        result = self.report("--since", "2026-03-05")
        self.assertEqual(result["summary"]["requests"], 2)
        self.assertAlmostEqual(result["summary"]["cost_usd"], 44.0)  # 40 fast output * 1.1 us
        self.assertEqual(result["summary"]["unpriced_requests"], 1)
        self.assertEqual(result["unpriced_models"], ["claude-unknown"])

    def test_tiered_prices_apply_per_request(self):
        rates = RATES["models"]["claude-test-small"]
        tokens = dict.fromkeys(usage.TOKEN_FIELDS + ("web_searches",), 0)
        tokens.update(cache_read=100_001, output=1_000_000)
        cost = usage.price(tokens, "claude-test-small", "standard", "", RATES)
        self.assertAlmostEqual(cost, (100_001 * rates["tiers"][0]["cache_read"] + 1_000_000 * 2.5) / 1e6)
        tokens["cache_read"] = 100_000
        self.assertAlmostEqual(usage.price(tokens, "claude-test-small", "standard", "", RATES), 0.501)

    def test_group_by_model_and_root(self):
        result = self.report("--by", "model", "--root", ENV_A)
        models = {item["model"]: item for item in result["items"]}
        self.assertEqual(set(models), {"claude-test-big", "claude-test-small"})
        self.assertEqual(models["claude-test-big"]["sessions"], 1)

    def write_rules(self, rules):
        path = Path(self.tmp.name) / "rules.json"
        path.write_text(json.dumps({"projects": rules}))
        return path

    def test_projects_match_cwd_branch_and_title(self):
        rules = self.write_rules([
            {"name": "feature-x", "branch": ["feat/*"]},
            {"name": "widgets", "title": ["*WIDGET*"]},
            {"name": "ring", "cwd": [ENV_B]},
        ])
        result = self.report("--projects", str(rules), "--by", "project")
        names = {item["project"]: item["requests"] for item in result["items"]}
        self.assertEqual(names, {"feature-x": 1, "widgets": 2, "ring": 2})

    def test_unmatched_requests_are_unassigned(self):
        result = self.report("--by", "project", "--by", "branch")
        keys = {(i["project"], i["branch"]) for i in result["items"]}
        self.assertIn(("unassigned", "repo@feat/x"), keys)
        self.assertIn(("unassigned", "left_pinky@main"), keys)

    def test_table_and_paging(self):
        text = self.run_cli("--format", "table", "--by", "day", "--limit", "1")
        self.assertIn("| day | sessions |", text)
        self.assertIn("**total**", text)
        self.assertIn("next --offset 1", text)
        self.assertIn("* includes requests with no rate (claude-unknown)", text)

    def test_missing_explicit_projects_file_is_refused(self):
        message = self.run_cli("--projects", "/nonexistent/rules.json", ok=False)
        self.assertIn("Token usage: projects file not found", message)

    def test_bad_timestamp_is_refused(self):
        self.assertIn("Token usage:", self.run_cli("--since", "yesterday", ok=False))

    def test_bundled_rates_cover_current_models(self):
        rates = json.loads((HELPER.parent / "rates.json").read_text())
        self.assertTrue(rates["source"].startswith("https://platform.claude.com/"))
        for model, table in rates["models"].items():
            with self.subTest(model=model):
                for field in ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read"):
                    self.assertGreater(table[field], 0)
                self.assertEqual(usage.model_key(model), model)


if __name__ == "__main__":
    unittest.main()
