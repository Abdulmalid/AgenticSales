import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class Cli(unittest.TestCase):
    """The CLI is how a business gets its first API key, so it must actually run end to end."""

    def run_cli(self, cwd: Path, *args: str) -> subprocess.CompletedProcess:
        # pin the data directory so the test behaves the same locally and in a container that sets AGENTIC_DATA_DIR
        env = {**os.environ, "PYTHONPATH": str(REPO), "PYTHONUTF8": "1", "AGENTIC_DATA_DIR": str(cwd / "data")}
        env.pop("GEMINI_API_KEY", None)
        env.pop("ANTHROPIC_API_KEY", None)
        return subprocess.run([sys.executable, "-m", "agentic_sales.cli", *args], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=60)

    def test_all_modules_compile(self):
        r = subprocess.run([sys.executable, "-m", "compileall", "-q", str(REPO / "agentic_sales")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_no_stray_control_characters_in_sources(self):
        """Regression: editing regexes through a shell once injected backspace characters into the code."""
        bad = []
        for p in list((REPO / "agentic_sales").rglob("*.py")) + list((REPO / "tests").rglob("*.py")):
            text = p.read_text(encoding="utf-8")
            if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                bad.append(str(p.relative_to(REPO)))
        self.assertEqual(bad, [])

    def test_tenant_create_issues_a_working_key_exactly_once(self):
        work = Path(tempfile.mkdtemp())
        cfg = work / "biz.json"
        cfg.write_text(json.dumps({"business_name": "Shop", "industry": "retail"}), encoding="utf-8")
        r = self.run_cli(work, "tenant-create", "--id", "shop-x", "--config", str(cfg))
        self.assertEqual(r.returncode, 0, r.stderr)
        key = r.stdout.strip().splitlines()[-1]
        self.assertTrue(key.startswith("ask_") and len(key) > 40)
        db = (work / "data" / "auth.db").read_bytes()
        self.assertNotIn(key.encode(), db)                       # only a hash is stored
        again = self.run_cli(work, "tenant-create", "--id", "shop-x", "--config", str(cfg))
        self.assertNotEqual(again.returncode, 0)                 # cannot silently overwrite a tenant

    def test_tenant_create_rejects_bad_config_and_bad_id(self):
        work = Path(tempfile.mkdtemp())
        cfg = work / "biz.json"
        cfg.write_text(json.dumps({"business_name": "", "industry": "x"}), encoding="utf-8")
        self.assertNotEqual(self.run_cli(work, "tenant-create", "--id", "ok-id", "--config", str(cfg)).returncode, 0)
        cfg.write_text(json.dumps({"business_name": "Shop", "industry": "x"}), encoding="utf-8")
        self.assertNotEqual(self.run_cli(work, "tenant-create", "--id", "../evil", "--config", str(cfg)).returncode, 0)
        self.assertFalse((work / "data" / "tenants" / "evil").exists())


if __name__ == "__main__":
    unittest.main()
