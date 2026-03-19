"""Tests for the PersistentMemoryStore (GAP 3)."""

from __future__ import annotations

import json
import time

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.persistent_memory import (
    DecisionRecord,
    LearnedPattern,
    PersistentMemoryStore,
    WorkRecord,
)


@pytest.fixture
def store(tmp_path):
    return PersistentMemoryStore(agent_name="test_bot", data_dir=tmp_path)


# ── Decisions ────────────────────────────────────────────────────────────────

class TestDecisions:
    def test_log_decision(self, store):
        record = store.log_decision("Use Stripe", reason="Lower fees", confidence=0.9)
        assert record.description == "Use Stripe"
        assert record.reason == "Lower fees"
        assert record.confidence == 0.9

    def test_get_decisions(self, store):
        store.log_decision("Decision A")
        store.log_decision("Decision B")
        decisions = store.get_decisions(limit=10)
        assert len(decisions) == 2

    def test_update_decision_outcome(self, store):
        record = store.log_decision("Test decision")
        assert store.update_decision_outcome(record.id, "success") is True
        decisions = store.get_decisions()
        found = [d for d in decisions if d["id"] == record.id]
        assert found[0]["outcome"] == "success"

    def test_filter_decisions_by_tags(self, store):
        store.log_decision("Tagged A", tags=["payment"])
        store.log_decision("Tagged B", tags=["shipping"])
        results = store.get_decisions(tags=["payment"])
        assert len(results) == 1
        assert results[0]["description"] == "Tagged A"

    def test_decision_persistence(self, tmp_path):
        store1 = PersistentMemoryStore(agent_name="test_bot", data_dir=tmp_path)
        store1.log_decision("Persistent decision")

        store2 = PersistentMemoryStore(agent_name="test_bot", data_dir=tmp_path)
        decisions = store2.get_decisions()
        assert len(decisions) == 1
        assert decisions[0]["description"] == "Persistent decision"


# ── Work history ─────────────────────────────────────────────────────────────

class TestWorkHistory:
    def test_log_work(self, store):
        record = store.log_work("Sent emails", success=True, duration_ms=500)
        assert record.description == "Sent emails"
        assert record.success is True

    def test_get_work_history(self, store):
        store.log_work("Task 1", success=True)
        store.log_work("Task 2", success=False, error="Timeout")
        history = store.get_work_history()
        assert len(history) == 2

    def test_filter_success_only(self, store):
        store.log_work("Good", success=True)
        store.log_work("Bad", success=False)
        results = store.get_work_history(success_only=True)
        assert len(results) == 1

    def test_work_summary(self, store):
        store.log_work("A", success=True, duration_ms=100)
        store.log_work("B", success=True, duration_ms=200)
        store.log_work("C", success=False, duration_ms=50)
        summary = store.work_summary()
        assert summary["total"] == 3
        assert summary["succeeded"] == 2
        assert summary["failed"] == 1
        assert summary["success_rate"] == pytest.approx(2/3, abs=0.01)


# ── Learned patterns ────────────────────────────────────────────────────────

class TestLearnedPatterns:
    def test_learn_pattern(self, store):
        pattern = store.learn_pattern("backoff", "Use exponential backoff")
        assert pattern.name == "backoff"
        assert pattern.confidence == 0.5

    def test_update_existing_pattern(self, store):
        store.learn_pattern("backoff", "Use backoff v1", confidence=0.5)
        updated = store.learn_pattern("backoff", "Use backoff v2", confidence=0.8)
        assert updated.description == "Use backoff v2"
        assert updated.confidence == 0.8

    def test_record_pattern_outcome(self, store):
        store.learn_pattern("retry", "Retry on failure")
        assert store.record_pattern_outcome("retry", success=True) is True
        pattern = store.get_pattern("retry")
        assert pattern["times_applied"] == 1
        assert pattern["times_succeeded"] == 1
        assert pattern["confidence"] > 0.5

    def test_pattern_confidence_decreases_on_failure(self, store):
        store.learn_pattern("bad_idea", "This approach", confidence=0.5)
        store.record_pattern_outcome("bad_idea", success=False)
        pattern = store.get_pattern("bad_idea")
        assert pattern["confidence"] < 0.5

    def test_get_patterns_min_confidence(self, store):
        store.learn_pattern("good", "Works well", confidence=0.9)
        store.learn_pattern("bad", "Doesn't work", confidence=0.1)
        results = store.get_patterns(min_confidence=0.5)
        assert len(results) == 1
        assert results[0]["name"] == "good"


# ── Interactions ─────────────────────────────────────────────────────────────

class TestInteractions:
    def test_log_interaction(self, store):
        record = store.log_interaction("user", "Hello there")
        assert record.role == "user"
        assert record.content == "Hello there"

    def test_get_interactions(self, store):
        store.log_interaction("user", "Hi")
        store.log_interaction("agent", "Hello!")
        interactions = store.get_interactions(limit=10)
        assert len(interactions) == 2


# ── State snapshots ──────────────────────────────────────────────────────────

class TestStateSnapshots:
    def test_save_snapshot(self, store):
        path = store.save_state_snapshot({"goals": 3, "tasks": 10}, label="test")
        assert path.exists()

    def test_get_latest_snapshot(self, store):
        store.save_state_snapshot({"version": 1})
        store.save_state_snapshot({"version": 2})
        latest = store.get_latest_snapshot()
        assert latest is not None
        assert latest["state"]["version"] == 2

    def test_list_snapshots(self, store):
        store.save_state_snapshot({"a": 1}, label="first")
        store.save_state_snapshot({"b": 2}, label="second")
        snaps = store.list_snapshots()
        assert len(snaps) == 2


# ── Export ───────────────────────────────────────────────────────────────────

class TestExport:
    def test_export_all(self, store):
        store.log_decision("D1")
        store.log_work("W1")
        store.learn_pattern("P1", "Pattern 1")

        export = store.export_all()
        assert export["agent_name"] == "test_bot"
        assert len(export["decisions"]) == 1
        assert len(export["work_history"]) == 1
        assert len(export["patterns"]) == 1
