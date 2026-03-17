"""
Tests for memory layer resilience improvements:
- semantic backend requirement and status
- retention/cleanup pruning
- vector consistency on delete
- legacy store compatibility + metadata repair
- recall retention pruning in tiered memory
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory.memory_manager import MemoryManager
from memory.tiered_memory import TieredMemoryManager


class _FakeVectorCollection:
    def __init__(self):
        self.docs: dict[str, tuple[str, dict]] = {}

    def upsert(self, ids, documents, metadatas):
        for doc_id, doc, meta in zip(ids, documents, metadatas):
            self.docs[doc_id] = (doc, meta)

    def delete(self, ids):
        for doc_id in ids:
            self.docs.pop(doc_id, None)

    def get(self):
        return {"ids": list(self.docs.keys())}

    def count(self):
        return len(self.docs)

    def query(self, **_kwargs):
        docs = [v[0] for v in self.docs.values()]
        metas = [v[1] for v in self.docs.values()]
        dists = [0.0 for _ in self.docs]
        return {
            "documents": [docs],
            "metadatas": [metas],
            "distances": [dists],
        }


class TestMemoryManagerResilience(unittest.TestCase):
    def test_require_vector_memory_raises_without_backend(self):
        with patch.dict(os.environ, {"AETHEERAI_REQUIRE_VECTOR_MEMORY": "1"}, clear=False):
            with self.assertRaises(RuntimeError):
                MemoryManager(persist=False, enable_vector=False)

    def test_delete_removes_vector_entry(self):
        m = MemoryManager(persist=False, enable_vector=False)
        m._vector_collection = _FakeVectorCollection()

        m.save("session_note", "hello")
        self.assertIn("session_note", m._vector_collection.docs)

        deleted = m.delete("session_note")
        self.assertTrue(deleted)
        self.assertNotIn("session_note", m._vector_collection.docs)

    def test_cleanup_prunes_expired_keys(self):
        with patch.dict(os.environ, {"AETHEERAI_MEMORY_RETENTION_DAYS": "0"}, clear=False):
            m = MemoryManager(persist=False, enable_vector=False)

        m.save("short_lived", "value", ttl_seconds=1)
        self.assertEqual(m.load("short_lived"), "value")

        ns_key = "short_lived"
        m._meta[ns_key]["expires_at"] = time.time() - 1
        report = m.cleanup(force=True)

        self.assertEqual(report["expired_removed"], 1)
        self.assertIsNone(m.load("short_lived"))

    def test_legacy_store_load_repairs_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            memory_file = tmp_path / "memory_store.json"
            memory_file.write_text(json.dumps({"legacy": {"x": 1}}), encoding="utf-8")

            with patch("memory.memory_manager._MEMORY_FILE", memory_file), patch(
                "memory.memory_manager._data_dir", return_value=tmp_path
            ), patch.dict(
                os.environ,
                {
                    "AETHEERAI_MEMORY_BACKUP_INTERVAL_SEC": "0",
                    "AETHEERAI_MEMORY_RETENTION_DAYS": "0",
                },
                clear=False,
            ):
                m = MemoryManager(persist=True, enable_vector=False)

            self.assertEqual(m.load("legacy"), {"x": 1})
            self.assertIn("legacy", m._meta)
            self.assertEqual(m._meta["legacy"]["namespace"], "global")

    def test_semantic_status_exposes_policy(self):
        with patch.dict(
            os.environ,
            {
                "AETHEERAI_MEMORY_RETENTION_DAYS": "14",
                "AETHEERAI_MEMORY_BACKUP_INTERVAL_SEC": "90",
            },
            clear=False,
        ):
            m = MemoryManager(persist=False, enable_vector=False)

        status = m.semantic_status()
        self.assertFalse(status["vector_available"])
        self.assertEqual(status["retention_days"], 14)
        self.assertEqual(status["backup_interval_sec"], 90)


class TestTieredMemoryRetention(unittest.TestCase):
    def test_recall_retention_prunes_stale_entries_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            recall_file = tmp_path / "recall_cache.json"
            old_ts = time.time() - (10 * 24 * 60 * 60)
            now = time.time()
            recall_file.write_text(
                json.dumps(
                    {
                        "old": {"value": "drop", "ts": old_ts},
                        "fresh": {"value": "keep", "ts": now},
                    }
                ),
                encoding="utf-8",
            )

            tm = TieredMemoryManager(
                recall_path=recall_file,
                recall_retention_days=2,
                recall_backup_keep=3,
                archival_manager=None,
            )

            self.assertNotIn("old", tm.recall_keys())
            self.assertIn("fresh", tm.recall_keys())


if __name__ == "__main__":
    unittest.main()
