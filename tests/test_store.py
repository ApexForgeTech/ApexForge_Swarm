import tempfile
import threading
import unittest
from pathlib import Path

from agent.store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def _store(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db = Path(tmpdir.name) / "sessions.db"
        return SessionStore(db)

    # ── Session API ────────────────────────────────────────────────────────

    def test_save_and_load_session(self):
        store = self._store()
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        store.save_session("sess-1", messages)
        loaded = store.load_session("sess-1")
        self.assertEqual(loaded, messages)

    def test_load_session_missing_returns_empty(self):
        store = self._store()
        self.assertEqual(store.load_session("nonexistent"), [])

    def test_save_session_upserts(self):
        store = self._store()
        store.save_session("sess-2", [{"role": "user", "content": "first"}])
        store.save_session("sess-2", [{"role": "user", "content": "updated"}])
        loaded = store.load_session("sess-2")
        self.assertEqual(loaded[0]["content"], "updated")

    def test_list_sessions_ordered_by_updated_at(self):
        store = self._store()
        store.save_session("sess-a", [])
        store.save_session("sess-b", [{"role": "user", "content": "hi"}])
        sessions = store.list_sessions()
        ids = [s["session_id"] for s in sessions]
        self.assertIn("sess-a", ids)
        self.assertIn("sess-b", ids)
        self.assertGreaterEqual(sessions[0]["updated_at"], sessions[-1]["updated_at"])

    def test_delete_session_existing(self):
        store = self._store()
        store.save_session("sess-del", [])
        deleted = store.delete_session("sess-del")
        self.assertTrue(deleted)
        self.assertEqual(store.load_session("sess-del"), [])

    def test_delete_session_nonexistent_returns_false(self):
        store = self._store()
        self.assertFalse(store.delete_session("ghost"))

    # ── Mission API ────────────────────────────────────────────────────────

    def test_create_and_get_mission(self):
        store = self._store()
        store.create_mission("m-1", "Analyze repo", provider="ollama", model="llama3")
        mission = store.get_mission("m-1")
        self.assertIsNotNone(mission)
        self.assertEqual(mission["prompt"], "Analyze repo")
        self.assertEqual(mission["status"], "running")
        self.assertEqual(mission["provider"], "ollama")
        self.assertEqual(mission["model"], "llama3")
        self.assertIsNone(mission["result"])

    def test_get_mission_nonexistent_returns_none(self):
        store = self._store()
        self.assertIsNone(store.get_mission("ghost"))

    def test_append_mission_event(self):
        store = self._store()
        store.create_mission("m-2", "Run task")
        store.append_mission_event("m-2", {"type": "info", "data": "step 1"})
        store.append_mission_event("m-2", {"type": "final", "data": "done"})
        mission = store.get_mission("m-2")
        self.assertEqual(len(mission["events"]), 2)
        self.assertEqual(mission["events"][0]["data"], "step 1")
        self.assertEqual(mission["events"][1]["type"], "final")

    def test_append_event_to_nonexistent_mission_is_noop(self):
        store = self._store()
        # should not raise
        store.append_mission_event("missing", {"type": "info", "data": "x"})

    def test_finish_mission_sets_result_and_status(self):
        store = self._store()
        store.create_mission("m-3", "Build feature")
        store.finish_mission("m-3", "Feature built successfully", status="completed")
        mission = store.get_mission("m-3")
        self.assertEqual(mission["status"], "completed")
        self.assertEqual(mission["result"], "Feature built successfully")
        self.assertIsNotNone(mission["finished_at"])

    def test_finish_mission_failed_status(self):
        store = self._store()
        store.create_mission("m-4", "Risky task")
        store.finish_mission("m-4", "", status="failed")
        self.assertEqual(store.get_mission("m-4")["status"], "failed")

    def test_list_missions_returns_recent_first(self):
        store = self._store()
        store.create_mission("m-old", "First task")
        store.create_mission("m-new", "Second task")
        missions = store.list_missions()
        ids = [m["mission_id"] for m in missions]
        self.assertIn("m-old", ids)
        self.assertIn("m-new", ids)
        self.assertGreaterEqual(
            missions[0]["created_at"], missions[-1]["created_at"]
        )

    def test_list_missions_filters_by_status(self):
        store = self._store()
        store.create_mission("m-run", "Running")
        store.create_mission("m-done", "Done")
        store.finish_mission("m-done", "ok", status="completed")
        running = store.list_missions(status="running")
        self.assertTrue(all(m["status"] == "running" for m in running))
        completed = store.list_missions(status="completed")
        self.assertTrue(all(m["status"] == "completed" for m in completed))

    def test_delete_mission_existing(self):
        store = self._store()
        store.create_mission("m-del", "Delete me")
        deleted = store.delete_mission("m-del")
        self.assertTrue(deleted)
        self.assertIsNone(store.get_mission("m-del"))

    def test_delete_mission_nonexistent_returns_false(self):
        store = self._store()
        self.assertFalse(store.delete_mission("ghost"))

    def test_stats_counts_sessions_and_missions(self):
        store = self._store()
        store.save_session("s1", [])
        store.save_session("s2", [])
        store.create_mission("m1", "Task A")
        store.create_mission("m2", "Task B")
        store.finish_mission("m2", "done", status="completed")
        stats = store.stats()
        self.assertEqual(stats["session_count"], 2)
        self.assertEqual(stats["mission_count"], 2)
        self.assertIn("running", stats["missions_by_status"])
        self.assertIn("completed", stats["missions_by_status"])
        self.assertEqual(stats["missions_by_status"]["running"], 1)
        self.assertEqual(stats["missions_by_status"]["completed"], 1)

    # ── Thread-safety ──────────────────────────────────────────────────────

    def test_concurrent_session_writes_are_safe(self):
        store = self._store()
        errors = []

        def write(idx):
            try:
                store.save_session(f"concurrent-{idx}", [{"role": "user", "content": str(idx)}])
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        sessions = store.list_sessions(limit=30)
        self.assertEqual(len(sessions), 20)
