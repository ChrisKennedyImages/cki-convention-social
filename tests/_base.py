"""Shared test scaffolding: every test gets its own DATA_ROOT, no .env file, no Keychain and no local Ollama."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from convention_social.core import config

SECRET_KEYS = ("CLASSIFY_BACKEND", "OLLAMA_MODEL", "OLLAMA_URL", "SMTP_PASSWORD", "ANTHROPIC_API_KEY", "BUFFER_API_KEY", "R2_KEY", "R2_SECRET",
               "MEDIA_UPLOAD_TOKEN", "GOOGLE_OAUTH_CLIENT_SECRET", "BRAND_NAME", "NTFY_TOPIC", "AI_MODEL", "GITHUB_TOKEN",
               "CLOUDFLARE_TUNNEL_TOKEN", "TUNNEL_HOSTNAME", "ACCESS_TEAM_DOMAIN", "ACCESS_AUD", "ACCESS_EMAIL")


class IsolatedCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._old_env = dict(os.environ)
        os.environ["CCS_DATA_ROOT"] = str(self.root / "data")
        os.environ["CCS_ENV_FILE"] = str(self.root / "absent.env")
        os.environ["SITE_HERO_SHIPPED"] = str(self.root / "no-shipped-hero.jpg")     # the repo's site/hero.jpg stays out of tests
        for key in SECRET_KEYS:
            os.environ.pop(key, None)
        config.reset()
        # the Mini keeps real keys in the Keychain and runs a real Ollama: no test may reach either
        # nor may a test start the designer in the background (each test that means to watch it patches it again)
        for target, value in (("convention_social.core.secrets._keychain", None),
                              ("convention_social.library.classify.ollama_model", None),
                              ("convention_social.render.design_samples.start_in_background", None),
                              ("convention_social.site.deploy.start_in_background", None)):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        config.reset()
        self._tmp.cleanup()
