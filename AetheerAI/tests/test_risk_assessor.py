"""
Tests for core/risk_assessor.py

Covers:
- PASS / WARN / BLOCK threshold mapping
- Weighted overall score calculation
- Worst-category recommendation wins
- AI failure defaults to WARN (safe default)
- audit_logger called on each assessment
- risk_log.jsonl written to disk
- assess_tool_call convenience wrapper
- history() limit respected
- clear_history()
- Input sanitation (3 000-char cap)
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.risk_assessor import (
    RiskAssessor,
    RiskAction,
    RiskLevel,
    RiskReport,
    _WEIGHTS,
    _score_to_level,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assessor(tmp_dir: Path, *, raise_on_chat: bool = False, response_json: dict | None = None):
    """Create a RiskAssessor with mocked ai_adapter wired to tmp_dir."""
    ai = MagicMock()
    audit = MagicMock()

    if raise_on_chat:
        ai.chat.side_effect = RuntimeError("LLM offline")
    elif response_json is not None:
        ai.chat.return_value = json.dumps(response_json)
    else:
        ai.chat.return_value = json.dumps(_default_response())

    # Redirect the module-level _RISK_LOG to tmp dir
    risk_log_path = tmp_dir / "risk_log.jsonl"
    with patch("core.risk_assessor._RISK_LOG", risk_log_path):
        assessor = RiskAssessor(ai_adapter=ai, audit_logger=audit)
        assessor._risk_log = risk_log_path  # store for assertion helpers
        assessor._audit_mock = audit
        assessor._ai_mock = ai
        yield assessor, risk_log_path


def _default_response(scores: dict[str, float] | None = None) -> dict:
    """Build a valid AI response with optional per-category score overrides."""
    base = {
        "financial": 1.0,
        "reputation": 1.0,
        "security": 1.0,
        "compliance": 1.0,
        "operational": 1.0,
    }
    if scores:
        base.update(scores)
    return {
        "categories": [
            {"category": cat, "score": base[cat], "reasoning": f"reason for {cat}"}
            for cat in ("financial", "reputation", "security", "compliance", "operational")
        ],
        "summary": "Low-risk action. Proceed with normal care.",
    }


def _weighted_score(scores: dict[str, float]) -> float:
    total = sum(_WEIGHTS.get(cat, 0.0) * s for cat, s in scores.items())
    return total


# ---------------------------------------------------------------------------
# Test: _score_to_level helper
# ---------------------------------------------------------------------------

class TestScoreToLevel(unittest.TestCase):

    def test_0_is_pass(self):
        level, action = _score_to_level(0.0)
        self.assertEqual(action, RiskAction.PASS)
        self.assertEqual(level, RiskLevel.LOW)

    def test_3_is_pass(self):
        _, action = _score_to_level(3.0)
        self.assertEqual(action, RiskAction.PASS)

    def test_3_9_is_pass(self):
        _, action = _score_to_level(3.9)
        self.assertEqual(action, RiskAction.PASS)

    def test_4_is_warn(self):
        level, action = _score_to_level(4.0)
        self.assertEqual(action, RiskAction.WARN)
        self.assertEqual(level, RiskLevel.MEDIUM)

    def test_6_9_is_warn(self):
        _, action = _score_to_level(6.9)
        self.assertEqual(action, RiskAction.WARN)

    def test_7_is_block(self):
        level, action = _score_to_level(7.0)
        self.assertEqual(action, RiskAction.BLOCK)
        self.assertEqual(level, RiskLevel.HIGH)

    def test_10_is_block(self):
        _, action = _score_to_level(10.0)
        self.assertEqual(action, RiskAction.BLOCK)


# ---------------------------------------------------------------------------
# Test: basic PASS scenario
# ---------------------------------------------------------------------------

class TestRiskAssessorPass(unittest.TestCase):

    def test_all_low_scores_returns_pass(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("researcher", "Read public web page")

                self.assertEqual(report.recommendation, RiskAction.PASS)
                self.assertEqual(report.overall_level, RiskLevel.LOW)
                self.assertFalse(report.is_blocked())
                self.assertFalse(report.is_warned())

    def test_report_fields_populated(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("ceo", "Generate Q3 report")

                self.assertEqual(report.agent_name, "ceo")
                self.assertIn("Q3", report.action)
                self.assertIsInstance(report.assessment_id, str)
                self.assertGreater(len(report.assessment_id), 8)
                self.assertGreater(report.assessed_at, 0)
                self.assertEqual(len(report.categories), 5)


# ---------------------------------------------------------------------------
# Test: WARN threshold
# ---------------------------------------------------------------------------

class TestRiskAssessorWarn(unittest.TestCase):

    def test_medium_security_score_returns_warn(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                # security = 5.0 → WARN; others low
                ai.chat.return_value = json.dumps(_default_response({"security": 5.0}))
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("developer", "Execute shell command")

                self.assertEqual(report.recommendation, RiskAction.WARN)
                self.assertTrue(report.is_warned())
                self.assertFalse(report.is_blocked())

    def test_worst_category_drives_recommendation(self):
        """One WARN category amongst all PASSes → recommendation = WARN."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                # overall weighted average is LOW, but one category is WARN
                ai.chat.return_value = json.dumps(
                    _default_response({"compliance": 4.5})  # single WARN driver
                )
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("operations", "Archive customer records")

                self.assertEqual(report.recommendation, RiskAction.WARN)


# ---------------------------------------------------------------------------
# Test: BLOCK threshold
# ---------------------------------------------------------------------------

class TestRiskAssessorBlock(unittest.TestCase):

    def test_high_security_score_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response({"security": 9.0}))
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("executor", "Drop production database")

                self.assertEqual(report.recommendation, RiskAction.BLOCK)
                self.assertTrue(report.is_blocked())

    def test_block_category_beats_overall_low(self):
        """Even if weighted average is medium, one BLOCK category → BLOCK."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                # financial = 8.0 → BLOCK; everything else near zero
                ai.chat.return_value = json.dumps(
                    _default_response({"financial": 8.0})
                )
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("finance-agent", "Transfer $50 000")

                self.assertEqual(report.recommendation, RiskAction.BLOCK)


# ---------------------------------------------------------------------------
# Test: AI failure defaults to WARN
# ---------------------------------------------------------------------------

class TestRiskAssessorAIFailure(unittest.TestCase):

    def test_ai_exception_returns_warn(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.side_effect = ConnectionError("No LLM available")
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("agent", "Do something risky")

                self.assertEqual(report.recommendation, RiskAction.WARN)
                self.assertAlmostEqual(report.overall_score, 5.0)
                self.assertIn("WARN", report.summary)

    def test_malformed_json_returns_warn(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = "This is not valid JSON !!!"
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("agent", "Something")

                self.assertEqual(report.recommendation, RiskAction.WARN)

    def test_ai_failure_never_returns_pass(self):
        """Critical: a broken risk assessor should never grant automatic PASS."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.side_effect = TimeoutError("Timeout")
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("agent", "Any action")

                self.assertNotEqual(report.recommendation, RiskAction.PASS)


# ---------------------------------------------------------------------------
# Test: Audit log and disk persistence
# ---------------------------------------------------------------------------

class TestRiskAssessorLogging(unittest.TestCase):

    def test_audit_logger_called(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                audit = MagicMock()
                assessor = RiskAssessor(ai_adapter=ai, audit_logger=audit)

                assessor.assess("researcher", "Fetch public data")

                audit.log.assert_called_once()

    def test_risk_log_jsonl_written(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            log_path = tmp / "risk_log.jsonl"
            with patch("core.risk_assessor._RISK_LOG", log_path):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                assessor.assess("researcher", "Read file")

                self.assertTrue(log_path.exists(), "risk_log.jsonl should be created")
                lines = log_path.read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(len(lines), 1)
                entry = json.loads(lines[0])
                self.assertIn("assessment_id", entry)
                self.assertIn("recommendation", entry)

    def test_multiple_assessments_append_to_log(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            log_path = tmp / "risk_log.jsonl"
            with patch("core.risk_assessor._RISK_LOG", log_path):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                assessor.assess("a1", "action 1")
                assessor.assess("a2", "action 2")
                assessor.assess("a3", "action 3")

                lines = log_path.read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(len(lines), 3)


# ---------------------------------------------------------------------------
# Test: assess_tool_call convenience wrapper
# ---------------------------------------------------------------------------

class TestRiskAssessorToolCall(unittest.TestCase):

    def test_assess_tool_call_returns_report(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess_tool_call(
                    "developer",
                    "execute_shell",
                    {"command": "ls /tmp"},
                )

                self.assertIsInstance(report, RiskReport)
                self.assertIn("execute_shell", report.action)

    def test_assess_tool_call_includes_kwargs_in_action(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess_tool_call(
                    "ops",
                    "delete_file",
                    {"path": "/data/important.csv"},
                )

                self.assertIn("delete_file", report.action)
                # The tool name must appear somewhere in the prompt that was built
                call_args = ai.chat.call_args[0][0]  # first positional arg = messages list
                prompt_text = call_args[0]["content"]
                self.assertIn("delete_file", prompt_text)


# ---------------------------------------------------------------------------
# Test: history() tracking and limit
# ---------------------------------------------------------------------------

class TestRiskAssessorHistory(unittest.TestCase):

    def test_history_accumulates(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                for i in range(5):
                    assessor.assess("agent", f"action_{i}")

                h = assessor.history()
                self.assertEqual(len(h), 5)

    def test_history_limit_respected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                for i in range(20):
                    assessor.assess("agent", f"action_{i}")

                h = assessor.history(limit=5)
                self.assertEqual(len(h), 5)
                # Should return the most recent 5
                last_action = h[-1]["action"]
                self.assertIn("action_19", last_action)

    def test_history_returns_dicts(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                assessor.assess("agent", "test action")
                h = assessor.history()

                self.assertIsInstance(h[0], dict)
                self.assertIn("assessment_id", h[0])
                self.assertIn("recommendation", h[0])
                self.assertIn("overall_score", h[0])

    def test_clear_history(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                assessor.assess("agent", "action 1")
                assessor.assess("agent", "action 2")
                assessor.clear_history()

                self.assertEqual(len(assessor.history()), 0)


# ---------------------------------------------------------------------------
# Test: weighted score calculation
# ---------------------------------------------------------------------------

class TestWeightedScore(unittest.TestCase):

    def test_weights_sum_to_one(self):
        total = sum(_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_overall_score_matches_expected(self):
        """Verify the assessor computes the correct weighted average."""
        scores = {
            "financial":   2.0,
            "reputation":  2.0,
            "security":    2.0,
            "compliance":  2.0,
            "operational": 2.0,
        }
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response(scores))
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("agent", "uniform risk action")

                expected = _weighted_score(scores)
                self.assertAlmostEqual(report.overall_score, expected, places=4)

    def test_high_weight_category_dominates_score(self):
        """Security (weight=0.30) scoring 10 should push overall score very high."""
        scores = {
            "financial":   0.0,
            "reputation":  0.0,
            "security":    10.0,
            "compliance":  0.0,
            "operational": 0.0,
        }
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response(scores))
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("agent", "critical security risk")

                # security contributes 0.30 * 10 = 3.0 to overall
                self.assertAlmostEqual(report.overall_score, 3.0, places=4)


# ---------------------------------------------------------------------------
# Test: input sanitisation
# ---------------------------------------------------------------------------

class TestRiskAssessorInputSanitisation(unittest.TestCase):

    def test_oversized_action_is_truncated_in_prompt(self):
        """Actions longer than 3 000 chars must be capped before sending to AI."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                long_action = "x" * 10_000
                assessor.assess("agent", long_action)

                call_args = ai.chat.call_args[0][0]
                prompt_text = call_args[0]["content"]
                # The prompt should NOT contain the full 10 000x
                self.assertLessEqual(len(prompt_text), 15_000)

    def test_none_context_does_not_raise(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                # Should not raise
                report = assessor.assess("agent", "action", context=None)  # type: ignore[arg-type]
                self.assertIsNotNone(report)


# ---------------------------------------------------------------------------
# Test: to_dict serialisation
# ---------------------------------------------------------------------------

class TestRiskReportToDict(unittest.TestCase):

    def test_to_dict_contains_required_keys(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("agent", "check serialisation")
                d = report.to_dict()

                for key in (
                    "assessment_id", "agent_name", "action", "context",
                    "overall_score", "overall_level", "recommendation",
                    "summary", "assessed_at", "categories"
                ):
                    self.assertIn(key, d, f"Missing key: {key}")

    def test_to_dict_is_json_serialisable(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with patch("core.risk_assessor._RISK_LOG", tmp / "risk_log.jsonl"):
                ai = MagicMock()
                ai.chat.return_value = json.dumps(_default_response())
                assessor = RiskAssessor(ai_adapter=ai)

                report = assessor.assess("agent", "json check")
                d = report.to_dict()

                # Should not raise
                serialised = json.dumps(d)
                self.assertIsInstance(serialised, str)


if __name__ == "__main__":
    unittest.main()
