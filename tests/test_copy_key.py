"""`bin/ccs copy-key`: Chris, 2026-10-11, "Use my Anthropic key from [my other suite's] .env (DO NOT TOUCH
ANYTHING IN THAT ENV)". The other file is only read and is byte for byte the same afterwards; the value
lands in this suite's .env and is never printed."""
from __future__ import annotations

import contextlib
import io
import os
from unittest import mock

from convention_social import cli
from convention_social.core import config, secrets
from tests._base import IsolatedCase

VALUE = "sk-ant-test-0123456789"


class CopyKey(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.src = self.root / "other" / ".env"
        self.src.parent.mkdir()
        self.src.write_text(f'# another suite\nFOO=1\nexport CLAUDE_API_KEY="{VALUE}"\nOTHER_SECRET=keep-me\n')
        os.utime(self.src, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        self.before = (self.src.read_bytes(), self.src.stat().st_mtime_ns)

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["copy-key", *args])
        return code, out.getvalue()

    def assert_source_untouched(self):
        self.assertEqual((self.src.read_bytes(), self.src.stat().st_mtime_ns), self.before)

    def test_the_key_is_copied_by_its_other_name_never_shown_and_the_source_untouched(self):
        code, out = self.run_cli("ANTHROPIC_API_KEY", "--from", str(self.src), "--no-check")
        self.assertEqual(code, 0)
        self.assertIn("read as CLAUDE_API_KEY", out)
        self.assertNotIn(VALUE, out)
        self.assertEqual(secrets.get_secret("ANTHROPIC_API_KEY"), VALUE)
        ours = config.env_file_path().read_text()
        self.assertIn(f"ANTHROPIC_API_KEY={VALUE}", ours)
        self.assertNotIn("OTHER_SECRET", ours, "only the one key comes across")
        self.assert_source_untouched()

    def test_its_own_name_wins_and_as_names_another(self):
        self.src.write_text(f"ANTHROPIC_API_KEY=first\nCLAUDE_API_KEY={VALUE}\nMY_KEY=mine\n")
        self.run_cli("ANTHROPIC_API_KEY", "--from", str(self.src), "--no-check")
        self.assertEqual(secrets.get_secret("ANTHROPIC_API_KEY"), "first")
        self.run_cli("ANTHROPIC_API_KEY", "--from", str(self.src), "--as", "MY_KEY", "--no-check")
        self.assertEqual(secrets.get_secret("ANTHROPIC_API_KEY"), "mine")

    def test_refusals_write_nothing(self):
        self.assertEqual(self.run_cli("SOME_RANDOM_KEY", "--from", str(self.src))[0], 2)
        self.assertEqual(self.run_cli("ANTHROPIC_API_KEY", "--from", str(self.root / "missing.env"))[0], 1)
        self.assertEqual(self.run_cli("BUFFER_API_KEY", "--from", str(self.src))[0], 1)            # not in that file
        self.assertFalse(config.env_file_path().exists())
        config.write_env({"FOO": "1"})
        self.assertEqual(self.run_cli("ANTHROPIC_API_KEY", "--from", str(config.env_file_path()))[0], 2)
        self.assert_source_untouched()

    def test_the_check_is_told_the_key_and_says_only_whether_it_was_accepted(self):
        seen = []
        with mock.patch.object(cli, "check_anthropic_key", lambda key: seen.append(key) or "Anthropic accepted it"):
            code, out = self.run_cli("ANTHROPIC_API_KEY", "--from", str(self.src))
        self.assertEqual((code, seen), (0, [VALUE]))
        self.assertIn("Anthropic accepted it", out)
        self.assertNotIn(VALUE, out)

    def test_the_check_is_one_free_model_list_call(self):
        import anthropic
        http = __import__("httpx2" if __import__("importlib").util.find_spec("httpx2") else "httpx")
        calls = []

        class Models:
            def __init__(self, fail):
                self.fail = fail

            def list(self, **kw):
                calls.append(kw)
                if self.fail:
                    raise anthropic.APIConnectionError(request=http.Request("GET", "https://api.anthropic.com/v1/models"))
                return []
        for fail, said in ((False, "Anthropic accepted it"), (True, "Anthropic did not accept it (APIConnectionError)")):
            with mock.patch.object(anthropic, "Anthropic", lambda api_key, fail=fail: mock.Mock(models=Models(fail))):
                self.assertEqual(cli.check_anthropic_key(VALUE), said)
        self.assertEqual(calls, [{"limit": 1}, {"limit": 1}])


class EnvCache(IsolatedCase):
    def test_the_dashboard_sees_a_key_saved_by_another_process(self):
        path = config.env_file_path()
        path.write_text("BRAND_DOMAIN=one.example\n")
        self.assertEqual(config.getenv("BRAND_DOMAIN"), "one.example")
        path.write_text("BRAND_DOMAIN=two.example\n")              # as the command line would, no reset() here
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        self.assertEqual(config.getenv("BRAND_DOMAIN"), "two.example")
