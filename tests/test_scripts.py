"""Tests for the helper scripts: temp folders only, no PhotoCraft needed.

Run from the repo root:
  python -E -m unittest discover -s tests -v        (python3 on macOS / Linux)
"""
import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

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
        self.assertEqual(code, 11)  # not 2, which means 'port held by something else'
        self.assertIn("invalid choice", out)
        self.assertEqual(run("photocraft-mcp.py", "status", "-Port", "abc")[0], 11)
        self.assertEqual(run("photocraft-mcp.py", "status", "-Port", "70000")[0], 11)

    def test_config_port(self):
        home = tempfile.mkdtemp()
        cfg = os.path.join(home, "config.env")
        with open(cfg, "w") as f:
            f.write("PHOTOCRAFT_PORT=7981  # LightCraft is 7980\n")
        # The inline comment is dropped, so the port parses and we get as far as 'not found'.
        code, out = run("photocraft-mcp.py", "status", "-PhotoCraftDir", home, env={"PHOTOCRAFT_HOME": home})
        self.assertEqual(code, 9, out)
        with open(cfg, "w") as f:
            f.write("PHOTOCRAFT_PORT=seventy\n")
        code, out = run("photocraft-mcp.py", "stop", env={"PHOTOCRAFT_HOME": home})
        self.assertEqual(code, 11, out)
        self.assertNotIn("Traceback", out)
        # An explicit -Port overrides the bad config line, and --help still works.
        code, out = run("photocraft-mcp.py", "status", "-Port", "7982", "-PhotoCraftDir", home,
                        env={"PHOTOCRAFT_HOME": home})
        self.assertEqual(code, 9, out)
        self.assertEqual(run("photocraft-mcp.py", "--help", env={"PHOTOCRAFT_HOME": home})[0], 0)

    def test_config_unclosed_quote(self):
        home = tempfile.mkdtemp()
        with open(os.path.join(home, "config.env"), "w") as f:
            f.write('PHOTOCRAFT_TOKEN_FILE="D:/t.txt\n')
        old = os.environ.get("PHOTOCRAFT_HOME")
        os.environ["PHOTOCRAFT_HOME"] = home
        try:
            import find_photocraft
            self.assertEqual(find_photocraft.config_value("PHOTOCRAFT_TOKEN_FILE"), "D:/t.txt")
        finally:
            if old is None:
                del os.environ["PHOTOCRAFT_HOME"]
            else:
                os.environ["PHOTOCRAFT_HOME"] = old

    def test_not_found(self):
        home = tempfile.mkdtemp()
        code, out = run("photocraft-mcp.py", "status", "-PhotoCraftDir", home, env={"PHOTOCRAFT_HOME": home})
        self.assertEqual(code, 9, out)


class TokenSafety(unittest.TestCase):
    TOK = "0123456789abcdef" * 4

    def test_token_given_as_path_is_refused(self):
        m = mcp()
        msg = m.check_token_file(self.TOK)
        self.assertIn("looks like a token", msg)
        self.assertNotIn(self.TOK, msg)
        self.assertIn("looks like a token", m.check_token_file(os.path.join(tempfile.mkdtemp(), self.TOK)))

    def test_scrub_next_to_word_characters(self):
        m = mcp()
        self.assertEqual(m.scrub(f"x_{self.TOK}_y"), "x_<token>_y")
        self.assertEqual(m.scrub("a" * 65), "a" * 65)  # a longer hex run isn't a token

    def test_say_scrubs(self):
        m = mcp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            m.say(f"token file: {self.TOK}")
        self.assertEqual(buf.getvalue().strip(), "token file: <token>")


class ProcessSelection(unittest.TestCase):
    def test_control_guis(self):
        m = mcp()
        procs = [(10, "photocraft.exe --control 7981 --control-token-file t"),
                 (11, "photocraft.exe --control 7982"),
                 (12, ""),                # command line unreadable
                 (13, "photocraft.exe")]  # the user's own PhotoCraft
        with mock.patch.object(m, "GUI_NAMES", ["photocraft.exe"]), \
                mock.patch.object(m, "processes", return_value=procs), \
                mock.patch.object(m, "listening", return_value=True), \
                mock.patch.object(m, "port_owner", return_value=None) as owner:
            self.assertEqual(list(m.control_guis(7981)), [10])
            owner.assert_not_called()  # a GUI started with --control wins; no guessing
            self.assertEqual(list(m.control_guis(7983)), [])  # owner unknown: never guess
            owner.return_value = 12
            self.assertEqual(list(m.control_guis(7983)), [12])  # the OS says 12 holds the port
            owner.return_value = 999  # another app holds the port
            self.assertEqual(list(m.control_guis(7983)), [])

    def test_bridge_pids_only_this_port(self):
        m = mcp()
        procs = [(1, "photocraft-cli.exe mcp --bridge 127.0.0.1:7981 --control-token-file t"),
                 (2, "photocraft-cli.exe mcp --bridge 127.0.0.1:7982 --control-token-file t"),
                 (3, "photocraft-cli.exe mcp --bridge 7981"),
                 (4, "photocraft-cli.exe run --bridge 127.0.0.1:7981"),
                 (5, "")]
        with mock.patch.object(m, "processes", return_value=procs):
            self.assertEqual(m.bridge_pids(7981), [1, 3])
            self.assertEqual(m.bridge_pids(7982), [2])

    def test_posix_processes_with_spaces(self):
        m = mcp()
        exe = "/Applications/ArtCraft PhotoCraft.app/Contents/MacOS/photocraft"
        outs = {"pid=,comm=": f"  42 {exe}\n  43 /usr/bin/photocraft-helper\n",
                "pid=,args=": f"  42 {exe} --control 7981 --automation-read-root /Users/me/My Photos\n"
                              "  43 /usr/bin/photocraft-helper\n"}

        def fake_run(args, **_kw):
            return subprocess.CompletedProcess(args, 0, outs[args[2]].encode(), b"")
        with mock.patch.object(m, "WIN", False), mock.patch.object(m, "run", side_effect=fake_run), \
                mock.patch.object(m, "_proc_cmdline", return_value=None):
            rows = m.processes("photocraft")
        self.assertEqual([p for p, _ in rows], [42])
        self.assertEqual(m.flag_values(rows[0][1], "--control"), ["7981"])

        def warns(cmd, want):
            buf = io.StringIO()
            with mock.patch.object(m, "MAC", True), contextlib.redirect_stdout(buf):
                m.report_roots(cmd, want, "")
            return "WARN" in buf.getvalue()
        self.assertFalse(warns(rows[0][1], ["/Users/me/My Photos"]))  # unquoted path with a space: granted
        self.assertTrue(warns(rows[0][1], ["/Users/me/Other"]))
        self.assertTrue(warns(rows[0][1], ["/Users/me/My"]))  # a prefix of a granted root isn't granted
        cmd2 = "/x/photocraft --automation-read-root /a b --control 7981"
        self.assertTrue(warns(cmd2, ["/a"]))
        self.assertFalse(warns(cmd2, ["/a b"]))

    def test_quote_args(self):
        m = mcp()
        cmd = m._quote_args(["/opt/pc/photocraft", "--automation-read-root", "/home/me/My Photos"])
        self.assertEqual(m.flag_values(cmd, "--automation-read-root"), ["/home/me/My Photos"])


class Bridge(unittest.TestCase):
    def reply(self, *objs, stderr=""):
        out = "".join(json.dumps(o) + "\n" for o in objs).encode()
        return subprocess.CompletedProcess([], 0, out, stderr.encode())

    def check(self, completed):
        m = mcp()
        with mock.patch.object(m, "run", return_value=completed):
            return m.bridge("cli", "127.0.0.1:7981", "t")

    def test_stages(self):
        init = {"id": 1, "result": {"serverInfo": {"version": "0.23.1"}}}
        ok = {"id": 2, "result": {"content": [{"type": "text", "text": "{}"}]}}
        self.assertEqual(self.check(self.reply(init, ok)), ("ok", "0.23.1"))
        self.assertEqual(self.check(self.reply({"id": 1, "result": None}))[0], "init")
        self.assertEqual(self.check(self.reply({"id": 1, "error": {"message": "x"}}))[0], "init")
        self.assertEqual(self.check(self.reply(stderr="boom"))[0], "init")
        bad = {"id": 2, "result": {"isError": True, "content": [
            {"type": "text", "text": "the app did not prove it holds this control token"}]}}
        self.assertEqual(self.check(self.reply(init, bad))[0], "token")
        self.assertEqual(self.check(self.reply(init, {"id": 2, "error": {"message": "x"}}))[0], "call")
        self.assertEqual(self.check(self.reply(init))[0], "call")


class FakeClaude:
    """Just enough of `claude mcp get/add/remove` for register()."""
    def __init__(self, entries):
        self.entries = dict(entries)  # scope -> (command, args)

    def __call__(self, args, **_kw):
        sub = args[2]
        if sub == "get":
            for scope in ("local", "project", "user"):
                if scope in self.entries:
                    c, a = self.entries[scope]
                    out = f"photocraft:\n  Scope: {scope.title()} config\n  Command: {c}\n  Args: {a}\n"
                    return subprocess.CompletedProcess(args, 0, out.encode(), b"")
            return subprocess.CompletedProcess(args, 1, b"", b"No MCP server")
        if sub == "add":
            scope = args[args.index("-s") + 1]
            rest = args[args.index("--") + 1:]
            self.entries[scope] = (rest[0], " ".join(rest[1:]))
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if sub == "remove":
            scope = args[args.index("-s") + 1]
            return subprocess.CompletedProcess(args, 0 if self.entries.pop(scope, None) else 1, b"", b"")
        raise AssertionError(args)


class Register(unittest.TestCase):
    def go(self, entries, scope="local"):
        m = mcp()
        fake = FakeClaude(entries)
        cli, tok = os.path.abspath("pc/photocraft-cli"), os.path.abspath("t/token.txt")
        with mock.patch.object(m, "claude_cmd", return_value="claude"), \
                mock.patch.object(m, "run", side_effect=fake), contextlib.redirect_stdout(io.StringIO()):
            rc = m.register(SimpleNamespace(Scope=scope), cli, "127.0.0.1:7981", tok)
        return rc, fake.entries, cli, tok

    def test_new_and_existing(self):
        rc, e, cli, tok = self.go({})
        self.assertEqual(rc, 0)
        self.assertEqual(e["local"], (cli, f"mcp --bridge 127.0.0.1:7981 --control-token-file {tok}"))
        rc, e2, _, _ = self.go(e)
        self.assertEqual((rc, e2), (0, e))

    def test_replaces_stale_local(self):
        rc, e, cli, _ = self.go({"local": ("old-cli", "mcp --bridge 127.0.0.1:7999 --control-token-file x")})
        self.assertEqual(rc, 0)
        self.assertEqual(e["local"][0], cli)

    def test_user_entry_left_alone(self):
        user = ("old-cli", "mcp --bridge 127.0.0.1:7999 --control-token-file x")
        rc, e, cli, _ = self.go({"user": user})
        self.assertEqual(rc, 0)
        self.assertEqual(e["user"], user)
        self.assertEqual(e["local"][0], cli)

    def test_project_entry_is_an_error(self):
        rc, e, _, _ = self.go({"project": ("other", "mcp")})
        self.assertEqual(rc, 6)
        self.assertNotIn("local", e)


class Stop(unittest.TestCase):
    def test_no_graceful_close_is_not_a_kill(self):
        m = mcp()
        a = SimpleNamespace(Port=7981, Force=False, TimeoutSec=1)
        with mock.patch.object(m, "claude_cmd", return_value=None), \
                mock.patch.object(m, "bridge_pids", return_value=[]), \
                mock.patch.object(m, "control_guis", return_value={5: "photocraft --control 7981"}), \
                mock.patch.object(m, "gui_pids", return_value=[5, 6]), \
                mock.patch.object(m, "restore_gui"), \
                mock.patch.object(m, "close_gui", return_value=False) as close, \
                mock.patch.object(m, "kill") as kill, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.stop(a), 7)
        kill.assert_not_called()
        self.assertEqual(close.call_args.kwargs, {"only_photocraft": False})  # pid 6 is another PhotoCraft

    def test_linux_close_targets_only_the_pid(self):
        m = mcp()
        listing = "0x01 0 5 host PhotoCraft\n0x02 0 6 host PhotoCraft\n0x03 0 5 host Panel\n"
        calls = []

        def fake_run(args, **_kw):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, listing.encode() if "-l" in args else b"", b"")
        with mock.patch.object(m, "WIN", False), mock.patch.object(m, "MAC", False), \
                mock.patch.object(m.shutil, "which", return_value="/usr/bin/wmctrl"), \
                mock.patch.object(m, "run", side_effect=fake_run):
            self.assertTrue(m.close_gui([5], only_photocraft=False))
        self.assertEqual([c[-1] for c in calls if "-c" in c], ["0x01", "0x03"])
        with mock.patch.object(m, "WIN", False), mock.patch.object(m, "MAC", False), \
                mock.patch.object(m.shutil, "which", return_value=None):
            self.assertFalse(m.close_gui([5], only_photocraft=True))


class FindExplicit(unittest.TestCase):
    def test_explicit_dir_is_searched_alone(self):
        from find_photocraft import CLI_NAME, find
        suite = tempfile.mkdtemp()
        inner = os.path.join(suite, "PhotoCraft")
        os.makedirs(inner)
        open(os.path.join(inner, CLI_NAME), "w").close()
        self.assertEqual(os.path.normcase(find(suite)), os.path.normcase(inner))
        self.assertEqual(find(tempfile.mkdtemp()), "")  # no fallback to the installed copy


class PortOwner(unittest.TestCase):
    def owner(self, win, outputs):
        m = mcp()

        def fake_run(args, **_kw):
            key = args[0]
            return subprocess.CompletedProcess(args, 0, outputs.get(key, "").encode(), b"")
        with mock.patch.object(m, "WIN", win), mock.patch.object(m, "run", side_effect=fake_run):
            return m.port_owner(7981)

    def test_windows(self):
        self.assertEqual(self.owner(True, {"powershell": "15244\r\n"}), 15244)
        netstat = ("  Proto  Local Address          Foreign Address        State           PID\r\n"
                   "  TCP    127.0.0.1:7980         0.0.0.0:0              LISTENING       111\r\n"
                   "  TCP    127.0.0.1:7981         0.0.0.0:0              LISTENING       222\r\n"
                   "  TCP    127.0.0.1:7981         127.0.0.1:5000         ESTABLISHED     333\r\n")
        self.assertEqual(self.owner(True, {"powershell": "", "netstat": netstat}), 222)
        self.assertIsNone(self.owner(True, {}))

    def test_posix(self):
        self.assertEqual(self.owner(False, {"lsof": "4242\n"}), 4242)
        self.assertIsNone(self.owner(False, {}))


class MacClose(unittest.TestCase):
    def close(self, only, rc=0):
        m = mcp()
        scripts = []

        def fake_run(args, **_kw):
            scripts.append(" ".join(args))
            return subprocess.CompletedProcess(args, rc, b"", b"")
        with mock.patch.object(m, "WIN", False), mock.patch.object(m, "MAC", True), \
                mock.patch.object(m, "run", side_effect=fake_run):
            ok = m.close_gui([77], only_photocraft=only)
        return ok, scripts

    def test_lone_photocraft_quits_by_name(self):
        ok, scripts = self.close(True)
        self.assertTrue(ok)
        self.assertIn("unix id is 77", scripts[0])
        self.assertIn("to quit", scripts[0])

    def test_with_another_photocraft_clicks_its_own_quit(self):
        ok, scripts = self.close(False)
        self.assertTrue(ok)
        self.assertIn("unix id is 77", scripts[0])
        self.assertIn("click q", scripts[0])
        self.assertNotIn("keystroke", scripts[0])  # never keyboard focus, which may be another app
        self.assertNotIn("to quit", scripts[0])    # quitting by name could quit the user's PhotoCraft

    def test_does_not_wait_for_the_save_prompt(self):
        for only in (True, False):
            self.assertIn("ignoring application responses", self.close(only)[1][0])

    def test_failure_is_reported(self):
        self.assertFalse(self.close(False, rc=1)[0])


if __name__ == "__main__":
    unittest.main()
