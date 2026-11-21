"""bench 套件的離線測試（不呼叫任何 API）。

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import metrics, runner  # noqa: E402
from bench.providers import REGISTRY, get  # noqa: E402
from bench.providers.base import Provider, ProviderError  # noqa: E402
from bench.providers.mock import MockBlind, MockOracle  # noqa: E402
from bench.schema import Part, Question, TaskError, load_tasks, parse_task  # noqa: E402


def text_task(items, qtype="binary", metric="classification", options=None):
    q = {"type": qtype, "instructions": "Q?"}
    if options:
        q["options"] = options
    return parse_task({"id": "t", "scenario": "zh_text", "metric": metric, "question": q, "items": items})


class SchemaTests(unittest.TestCase):
    def test_all_task_files_parse(self):
        tasks = load_tasks()
        self.assertGreaterEqual(len(tasks), 15)
        for t in tasks:
            for it in t.items:
                self.assertIn(it.gold if t.scored else "yes", t.question_for(it).labels if t.scored else ["yes"])

    def test_committed_media_exist(self):
        """影像任務的圖檔都要存在（音訊素材不進版控，略過）。"""
        for t in load_tasks(["image"]):
            for it in t.items:
                for p in it.inputs:
                    if p.path:
                        self.assertTrue((ROOT / p.path).is_file(), p.path)

    def test_gold_must_be_valid_label(self):
        with self.assertRaises(TaskError):
            text_task([{"id": "a", "inputs": [{"type": "text", "text": "x"}], "gold": "maybe"}])

    def test_duplicate_ids_rejected(self):
        row = {"id": "a", "inputs": [{"type": "text", "text": "x"}], "gold": "yes"}
        with self.assertRaises(TaskError):
            text_task([row, row])

    def test_swap_requires_pair(self):
        with self.assertRaises(TaskError):
            text_task([{"id": "a", "inputs": [{"type": "text", "text": "x"}]}], metric="swap_symmetry")

    def test_vars_render(self):
        q = Question("binary", "Target: {target}")
        self.assertEqual(q.render({"target": "你好"}).instructions, "Target: 你好")


class MetricTests(unittest.TestCase):
    def test_auc(self):
        self.assertEqual(metrics.auc([0.9, 0.8], [0.1, 0.2]), 1.0)
        self.assertEqual(metrics.auc([0.5], [0.5]), 0.5)
        self.assertIsNone(metrics.auc([], [0.1]))

    def test_classification_perfect_and_uniform(self):
        labels = ["yes", "no"]
        perfect = [{"ok": True, "gold": "yes", "probs": {"yes": 1.0, "no": 0.0}},
                   {"ok": True, "gold": "no", "probs": {"yes": 0.0, "no": 1.0}}]
        m = metrics.classification(perfect, labels)
        self.assertEqual(m["accuracy"], 1.0)
        self.assertEqual(m["auc"], 1.0)
        self.assertAlmostEqual(m["brier"], 0.0)
        uniform = [{"ok": True, "gold": g, "probs": {"yes": 0.5, "no": 0.5}} for g in ("yes", "no")]
        self.assertAlmostEqual(metrics.classification(uniform, labels)["brier"], 0.5)

    def test_errors_counted_not_scored(self):
        recs = [{"ok": False, "gold": "yes"}, {"ok": True, "gold": "yes", "probs": {"yes": 0.9}}]
        m = metrics.classification(recs, ["yes", "no"])
        self.assertEqual((m["n"], m["n_ok"], m["n_err"]), (2, 1, 1))
        self.assertEqual(m["accuracy"], 1.0)

    def test_normalize_fills_missing(self):
        self.assertEqual(metrics.normalize({"a": 2.0}, ["a", "b"]), {"a": 1.0, "b": 0.0})
        self.assertEqual(metrics.normalize({}, ["a", "b"]), {"a": 0.5, "b": 0.5})

    def test_ece_perfectly_calibrated(self):
        recs = [{"gold": "yes", "probs": {"yes": 1.0, "no": 0.0}}] * 4
        self.assertAlmostEqual(metrics.ece(recs, ["yes", "no"]), 0.0)

    def test_per_item_multiclass(self):
        recs = [{"ok": True, "item": "a", "gold": "x", "probs": {"x": 1.0, "y": 0.0, "z": 0.0}},
                {"ok": True, "item": "b", "gold": "q", "probs": {"p": 1.0, "q": 0.0}}]
        m = metrics.classification_per_item(recs, {"a": ["x", "y", "z"], "b": ["p", "q"]})
        self.assertEqual(m["correct"], 1)
        self.assertAlmostEqual(m["brier"], 1.0)   # (0 + 2) / 2

    def test_swap_symmetry(self):
        recs = [{"ok": True, "pair": "p1", "side": "a", "item": "p1a", "probs": {"yes": 0.8, "no": 0.2}},
                {"ok": True, "pair": "p1", "side": "b", "item": "p1b", "probs": {"yes": 0.5, "no": 0.5}}]
        m = metrics.swap_symmetry(recs)
        self.assertAlmostEqual(m["mean_abs_delta"], 0.3)
        self.assertAlmostEqual(m["mean_signed_delta"], 0.3)
        self.assertAlmostEqual(metrics.swap_symmetry(recs, polarity={"p1": -1})["favor_a"], -0.3)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.patches = [mock.patch.object(runner, "CACHE_DIR", base / "cache"),
                        mock.patch.object(runner, "RESULTS_DIR", base / "results"),
                        mock.patch.object(runner, "CAPS_FILE", base / "results" / "capabilities.json")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _task(self):
        rows = [{"id": f"i{n}", "inputs": [{"type": "text", "text": f"GOLD={g} item {n}"}], "gold": g}
                for n, g in enumerate(["yes", "no", "yes", "no"])]
        return text_task(rows)

    def test_oracle_scores_perfect_and_caches(self):
        task = self._task()
        out = runner.run([MockOracle()], [task], budget_usd=1, log=lambda *_: None, run_id="r1")
        recs = [json.loads(l) for l in (out / "records.jsonl").read_text().splitlines()]
        self.assertEqual(len(recs), 4)
        self.assertEqual(metrics.classification(recs, ["yes", "no"])["accuracy"], 1.0)
        self.assertFalse(any(r["cached"] for r in recs))
        out2 = runner.run([MockOracle()], [task], budget_usd=1, log=lambda *_: None, run_id="r2")
        recs2 = [json.loads(l) for l in (out2 / "records.jsonl").read_text().splitlines()]
        self.assertTrue(all(r["cached"] for r in recs2))

    def test_unprobed_modality_is_skipped(self):
        task = parse_task({"id": "img", "scenario": "image", "question": {"type": "binary", "instructions": "?"},
                           "items": [{"id": "a", "inputs": [{"type": "image", "path": "bench/fixtures/red.png"}],
                                      "gold": "yes"}]})
        cells = runner.plan([MockOracle()], [task], caps={})
        self.assertFalse(cells[0]["run"])
        self.assertEqual(cells[0]["reason"], "modality:image=unprobed")
        caps = {"mock-oracle": {"image": {"status": "supported"}}}
        self.assertTrue(runner.plan([MockOracle()], [task], caps=caps)[0]["run"])

    def test_budget_stops_run(self):
        class Pricey(MockBlind):
            info = MockBlind.info.__class__(**{**MockBlind.info.__dict__, "id": "pricey", "usd_per_question": 1.0})
        out = runner.run([Pricey()], [self._task()], budget_usd=1.5, workers=1, log=lambda *_: None, run_id="b")
        meta = json.loads((out / "meta.json").read_text())
        self.assertIn("預算上限", meta["stopped"])

    def test_label_mismatch_not_scored(self):
        class Wrong(MockBlind):
            def send(self, req):
                return {"probs": {"maybe": 1.0}, "tokens": 1}
        rec = runner.call(Wrong(), self._task(), self._task().items[0], None, use_cache=False)
        self.assertFalse(rec["ok"])
        self.assertIn("標籤或機率不符", rec["error"])

    def test_provider_error_recorded(self):
        class Broken(MockBlind):
            def send(self, req):
                raise ProviderError("HTTP 500: boom", 500)
        rec = runner.call(Broken(), self._task(), self._task().items[0], None, use_cache=False)
        self.assertFalse(rec["ok"])
        self.assertIn("500", rec["error"])


class DashboardTests(unittest.TestCase):
    def test_build_data_shape_and_composite_rule(self):
        from bench import dashboard
        data = dashboard.build_data()
        self.assertEqual(len(data["models"]), len(REGISTRY))
        for m in data["models"]:
            self.assertIn(m["tier"], ("text", "image", "audio"))
            has_all = all("acc" in m["tasks"].get(t, {}) for t in dashboard.DISCRIMINATIVE)
            self.assertEqual(m["composite"] is not None, has_all, m["id"])
            if m["tier"] == "text":
                self.assertIsNone(m["composite"], f"{m['id']} 是純文字模型，不應有綜合分數")

    def test_template_has_placeholder(self):
        from bench import dashboard
        self.assertIn("/*__DATA__*/null", dashboard.TEMPLATE.read_text(encoding="utf-8"))


class ProviderShapeTests(unittest.TestCase):
    """各 adapter 的請求／回應轉換（不連網）。"""

    def test_every_registered_provider_builds_requests(self):
        parts = [Part("text", text="hello")]
        for pid, cls in REGISTRY.items():
            prov = cls()
            with mock.patch.dict("os.environ", {k: "test-key" for k in prov.info.env_keys}):
                for q in (Question("binary", "Is it?"), Question("choice", "Which?", {"a": "A", "b": "B"})):
                    req = prov.build_request(parts, q)
                    self.assertTrue(req.url.startswith("https://"), pid)
                    self.assertNotIn("test-key", json.dumps(req.cache_payload()), f"{pid} 快取鍵含金鑰")

    def test_gemini_parse(self):
        g = REGISTRY["gemini-decision-1"]()
        a = g.parse_response({"answers": {"q": {"noul": 0.7}}, "usage": {"total_input_tokens": 50}},
                             Question("binary", "?"))
        self.assertAlmostEqual(a.probs["yes"], 0.7)
        self.assertEqual(a.input_tokens, 50)
        a = g.parse_response({"answers": {"q": {"probabilities": {"a": 0.2, "b": 0.8}}}},
                             Question("choice", "?", {"a": "A", "b": "B"}))
        self.assertEqual(a.probs["b"], 0.8)

    def test_get_rejects_unknown(self):
        with self.assertRaises(SystemExit):
            get(["no-such-model"])


if __name__ == "__main__":
    unittest.main()
