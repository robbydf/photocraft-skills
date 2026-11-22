"""Tests for the helper scripts: temp folders only, no PhotoCraft needed.

Run from the repo root:
  python -E -m unittest discover -s tests -v        (python3 on macOS / Linux)
"""
import importlib
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)


def run(script, *args, env=None):
    """Run a script with this interpreter; returns (code, stdout+stderr)."""
    e = dict(os.environ, **(env or {}))
    r = subprocess.run([sys.executable, "-E", os.path.join(SCRIPTS, script), *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8", env=e)
    return r.returncode, r.stdout + r.stderr


def mcp():
    return importlib.import_module("photocraft-mcp")


class PcArgs(unittest.TestCase):
    def test_fix_argv(self):
        from pcargs import fix_argv
        out = fix_argv(["start", "-readroot", "C:/a", "-ReadRoot", "C:/b", "-port", "7999", "-force"],
                       ["-ReadRoot", "-Port"], ["-Force"])
        self.assertEqual(out, ["start", "-ReadRoot=C:/a", "-ReadRoot=C:/b", "-Port=7999", "-Force"])


class FindPhotoCraft(unittest.TestCase):
    def test_env_dir_and_arg(self):
        from find_photocraft import CLI_NAME
        d = tempfile.mkdtemp()
        open(os.path.join(d, CLI_NAME), "w").close()
        home = tempfile.mkdtemp()
        code, out = run("find_photocraft.py", env={"PHOTOCRAFT_DIR": d, "PHOTOCRAFT_HOME": home})
        self.assertEqual(code, 0, out)
        self.assertEqual(os.path.normcase(out.strip()), os.path.normcase(d))
        code, out = run("find_photocraft.py", "--dir", d, env={"PHOTOCRAFT_HOME": home})
        self.assertEqual(os.path.normcase(out.strip()), os.path.normcase(d))

    def test_config_dir_and_values(self):
        from find_photocraft import CLI_NAME
        d = tempfile.mkdtemp()
        open(os.path.join(d, CLI_NAME), "w").close()
        home = tempfile.mkdtemp()
        with open(os.path.join(home, "config.env"), "w", encoding="utf-8") as f:
            f.write(f'# comment\nPHOTOCRAFT_DIR="{d}"\nPHOTOCRAFT_READ_ROOT=/a\nPHOTOCRAFT_READ_ROOT=/b\n')
        env = {k: v for k, v in os.environ.items() if k != "PHOTOCRAFT_DIR"}
        env["PHOTOCRAFT_HOME"] = home
        r = subprocess.run([sys.executable, "-E", os.path.join(SCRIPTS, "find_photocraft.py")],
                           capture_output=True, text=True, env=env)
        self.assertEqual(os.path.normcase(r.stdout.strip()), os.path.normcase(d))
        old = os.environ.get("PHOTOCRAFT_HOME")
        os.environ["PHOTOCRAFT_HOME"] = home
        try:
            import find_photocraft
            self.assertEqual(find_photocraft.config_values("PHOTOCRAFT_READ_ROOT"), ["/a", "/b"])
            self.assertEqual(find_photocraft.config_value("PHOTOCRAFT_WRITE_ROOT"), "")
        finally:
            if old is None:
                del os.environ["PHOTOCRAFT_HOME"]
            else:
                os.environ["PHOTOCRAFT_HOME"] = old

    def test_help_and_usage(self):
        code, out = run("find_photocraft.py", "--help")
        self.assertEqual(code, 0)
        self.assertIn("Usage", out)
        self.assertEqual(run("find_photocraft.py", "--bogus")[0], 2)


class TokenFile(unittest.TestCase):
    def test_check_token_file(self):
        m = mcp()
        d = tempfile.mkdtemp()
        self.assertIn("no token file", m.check_token_file(""))
        self.assertEqual(m.check_token_file(os.path.join(d, "new.txt")), "")  # PhotoCraft creates it
        self.assertIn("does not exist", m.check_token_file(os.path.join(d, "nope", "t.txt")))
        self.assertIn("is a folder", m.check_token_file(d))
        good, bad = os.path.join(d, "good.txt"), os.path.join(d, "bad.txt")
        with open(good, "w") as f:
            f.write("ab" * 32 + "\n")
        with open(bad, "w") as f:
            f.write("not a token")
        self.assertEqual(m.check_token_file(good), "")
        msg = m.check_token_file(bad)
        self.assertIn("64-hex", msg)
        self.assertNotIn("not a token", msg)

    def test_scrub(self):
        m = mcp()
        tok = "0123456789abcdef" * 4
        self.assertEqual(m.scrub(f"err {tok} x"), "err <token> x")


class CommandLine(unittest.TestCase):
    def test_flag_values(self):
        m = mcp()
        cmd = ('"C:\\PC\\photocraft.exe" --control 7981 --control-token-file D:/t.txt '
               '--automation-read-root "C:\\My Photos" --automation-read-root=E:/x --automation-write-root C:/out')
        self.assertEqual(m.flag_values(cmd, "--control"), ["7981"])
        self.assertEqual(m.flag_values(cmd, "--automation-read-root"), ["C:\\My Photos", "E:/x"])
        self.assertEqual(m.flag_values(cmd, "--automation-write-root"), ["C:/out"])
        self.assertEqual(m.flag_values(cmd, "--control-token-file"), ["D:/t.txt"])

    def test_registration_match(self):
        m = mcp()
        cli = os.path.abspath("pc/photocraft-cli")
        tok = os.path.abspath("t/token.txt")
        reg = ("local", cli, f"mcp --bridge 127.0.0.1:7981 --control-token-file {tok}")
        self.assertTrue(m.matches(reg, cli, "127.0.0.1:7981", tok))
        self.assertFalse(m.matches(reg, cli, "127.0.0.1:7982", tok))
        self.assertFalse(m.matches(reg, cli, "127.0.0.1:7981", os.path.abspath("other.txt")))
        self.assertFalse(m.matches(("local", cli, "mcp --bridge 127.0.0.1:7981"), cli, "127.0.0.1:7981", tok))
        self.assertFalse(m.matches(None, cli, "127.0.0.1:7981", tok))


class Usage(unittest.TestCase):
    def test_bad_action(self):
        code, out = run("photocraft-mcp.py", "bogus")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", out)

    def test_not_found(self):
        home = tempfile.mkdtemp()
        code, out = run("photocraft-mcp.py", "status", "-PhotoCraftDir", home, env={"PHOTOCRAFT_HOME": home})
        self.assertEqual(code, 9, out)


if __name__ == "__main__":
    unittest.main()
