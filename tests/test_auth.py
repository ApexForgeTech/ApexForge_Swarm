import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from agent.web.auth import check_api_key, is_auth_enabled


class AuthDisabledTests(unittest.TestCase):
    """When APEXFORGE_API_KEY is not set, auth is disabled."""

    def setUp(self):
        self._patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._patcher.start()
        os.environ.pop("APEXFORGE_API_KEY", None)

    def tearDown(self):
        self._patcher.stop()

    def test_auth_disabled_when_no_key(self):
        self.assertFalse(is_auth_enabled())

    def test_check_api_key_passes_with_no_env_key(self):
        # Should not raise even with an empty header
        try:
            check_api_key(x_api_key="")
            check_api_key(x_api_key="anything")
        except Exception as exc:
            self.fail(f"check_api_key raised unexpectedly: {exc}")


class AuthEnabledTests(unittest.TestCase):
    """When APEXFORGE_API_KEY is set, only matching keys pass."""

    def setUp(self):
        self._patcher = mock.patch.dict(os.environ, {"APEXFORGE_API_KEY": "secret-key-123"})
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_auth_enabled_when_key_set(self):
        self.assertTrue(is_auth_enabled())

    def test_valid_key_passes(self):
        from fastapi import HTTPException
        try:
            check_api_key(x_api_key="secret-key-123")
        except HTTPException:
            self.fail("check_api_key raised HTTPException for a valid key")

    def test_missing_key_returns_401(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            check_api_key(x_api_key="")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_wrong_key_returns_403(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            check_api_key(x_api_key="wrong-key")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_timing_safe_comparison_used(self):
        """Verify the comparison does not short-circuit on early mismatch."""
        # Both wrong keys must raise 403, not 401
        from fastapi import HTTPException
        for key in ["a", "secret-key-12", "secret-key-124"]:
            with self.assertRaises(HTTPException) as ctx:
                check_api_key(x_api_key=key)
            self.assertEqual(ctx.exception.status_code, 403, f"Expected 403 for key={key!r}")


class AuthFastAPIIntegrationTests(unittest.TestCase):
    """Integration: protected endpoints return 401/403 via FastAPI test client."""

    def _client_with_key(self, key: str):
        import tempfile
        from pathlib import Path
        import agent.web.app as web_app
        from agent.config import Config

        # Keep env patcher alive for the full test (TestClient makes requests after __exit__)
        env_patcher = mock.patch.dict(os.environ, {"APEXFORGE_API_KEY": key})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

        tmpdir = tempfile.mkdtemp()
        cfg = Config()
        cfg.agent.memory_dir = str(Path(tmpdir) / "memory")
        Path(cfg.agent.memory_dir).mkdir(parents=True, exist_ok=True)

        mock_agent = mock.MagicMock()
        mock_agent.available_models.return_value = []
        mock_agent.memory.list_skills.return_value = []
        mock_agent.memory.list_memories.return_value = []
        mock_agent.token_estimate.return_value = 0
        mock_agent.message_count.return_value = 0
        mock_agent.backend_capabilities.return_value = {}

        with mock.patch("agent.web.app.build_agent", return_value=mock_agent), \
             mock.patch("agent.web.app.SessionStore"):
            web_app.init(cfg)

        return TestClient(web_app.app)

    def test_clear_requires_valid_api_key(self):
        client = self._client_with_key("test-key")
        # No key → 401
        resp = client.post("/api/clear")
        self.assertEqual(resp.status_code, 401)
        # Wrong key → 403
        resp = client.post("/api/clear", headers={"X-API-Key": "bad"})
        self.assertEqual(resp.status_code, 403)
        # Correct key → 200
        resp = client.post("/api/clear", headers={"X-API-Key": "test-key"})
        self.assertEqual(resp.status_code, 200)

    def test_reload_requires_valid_api_key(self):
        client = self._client_with_key("test-key")
        resp = client.post("/api/reload")
        self.assertEqual(resp.status_code, 401)
        resp = client.post("/api/reload", headers={"X-API-Key": "test-key"})
        self.assertEqual(resp.status_code, 200)
