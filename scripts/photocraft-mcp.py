"""photocraft-mcp: start / stop the PhotoCraft GUI with its control port + the CLI MCP bridge, and
(dis)connect Claude Code.

Usage: python photocraft-mcp.py start|stop|status [-Port 7981] [-TokenFile FILE] [-ReadRoot DIR]...
                                [-WriteRoot DIR] [-Scope local|user] [-TimeoutSec 60] [-Force]
                                [-PhotoCraftDir DIR]
(python3 on macOS / Linux). Standard library only.

The control port needs a token (64 hex digits) held in a file. The file comes from -TokenFile, else
$PHOTOCRAFT_CONTROL_TOKEN_FILE, else PHOTOCRAFT_TOKEN_FILE= in ~/.claude/photocraft/config.env
($PHOTOCRAFT_HOME). PhotoCraft creates the file when it is missing. The token itself is never printed;
Claude Code's registration holds only the file's path.

Automation roots (the folders MCP tools may read from / write to) are set when the GUI starts:
-ReadRoot (repeat for more; else PHOTOCRAFT_READ_ROOT= lines in config.env) and -WriteRoot (one; else
PHOTOCRAFT_WRITE_ROOT=). Without them the bridge can drive the GUI but can't open or save files.

Exit codes: 2 the port is held by something that can't prove the token (another app, or a PhotoCraft
started with another token), 3 the port never opened, 4 the bridge initialize failed, 5 the bridge
could not drive the GUI, 6 `claude mcp add` failed (or claude not found, or a project .mcp.json
registers another command), 7 stop: the GUI is still open, 8 stop: the registration is still there,
9 PhotoCraft not found, 10 no usable token file.
"""
import argparse
import csv
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from find_photocraft import CLI_NAME, config_value, config_values, find  # noqa: E402
from pcargs import fix_argv  # noqa: E402

WIN = os.name == "nt"
MAC = sys.platform == "darwin"
NAME = "photocraft"
GUI_NAMES = ["photocraft.exe"] if WIN else ["photocraft", "PhotoCraft"]
TOKEN_RE = re.compile(r"^[0-9a-fA-F]{64}$")
TOKEN_MISMATCH = "did not prove it holds this control token"
if WIN:
    LOG_HINT = r"%APPDATA%\PhotoCraft\logs\photocraft.log"
elif MAC:
    LOG_HINT = "~/Library/Application Support/PhotoCraft/logs/photocraft.log"
else:
    LOG_HINT = "~/.local/share/PhotoCraft/logs/photocraft.log"


def say(s):
    print(s, flush=True)


def run(args, timeout=60, **kw):
    """Run a command; never raise for a missing program or a timeout."""
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout, **kw)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(args, -9, e.stdout or b"", e.stderr or b"")
    except OSError as e:
        return subprocess.CompletedProcess(args, -1, b"", str(e).encode())


def text(b):
    return (b or b"").decode("utf-8", "replace")


def scrub(s):
    """Never echo a token, even inside an error message."""
    return re.sub(r"\b[0-9a-fA-F]{64}\b", "<token>", s)


def listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p))) if p else ""


# ---------------------------------------------------------------- processes

def processes(image):
    """[(pid, command line)] of processes with this executable name ('' command line if unknown)."""
    rows = []
    if WIN:
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='%s'\" | "
              "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }" % image)
        r = run(["powershell", "-NoProfile", "-Command", ps])
        for line in text(r.stdout).splitlines():
            pid, _, cmd = line.partition("\t")
            if pid.strip().isdigit():
                rows.append((int(pid.strip()), cmd.strip()))
        if not rows:  # no PowerShell / CIM: pids only
            r = run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"])
            rows = [(int(row[1]), "") for row in csv.reader(io.StringIO(text(r.stdout)))
                    if len(row) > 1 and row[0].lower() == image.lower() and row[1].isdigit()]
    else:
        r = run(["ps", "-axo", "pid=,args="])
        for line in text(r.stdout).splitlines():
            pid, _, cmd = line.strip().partition(" ")
            exe = cmd.split(" ", 1)[0]
            if pid.isdigit() and os.path.basename(exe) == image:
                rows.append((int(pid), cmd))
    return rows


def flag_values(cmd, flag):
    """Values of `--flag value` / `--flag=value` / `--flag "a b"` in a command line."""
    return [m.group(1) or m.group(2) for m in
            re.finditer(r'(?:^|\s)' + re.escape(flag) + r'(?:=|\s+)(?:"([^"]*)"|(\S+))', cmd)]


def gui_pids():
    return [p for name in GUI_NAMES for p, _ in processes(name)]


def control_guis(port):
    """{pid: command line} of PhotoCraft GUIs started with --control on this port.
    A GUI whose command line is unknown, or that took the port from PHOTOCRAFT_CONTROL_PORT, counts
    when the port is listening and it is the only GUI with no --control flag."""
    out, unknown = {}, []
    for name in GUI_NAMES:
        for pid, cmd in processes(name):
            ports = flag_values(cmd, "--control")
            if str(port) in ports:
                out[pid] = cmd
            elif not ports:
                unknown.append((pid, cmd))
    if not out and len(unknown) == 1 and not unknown[0][1] and listening(port):
        out[unknown[0][0]] = ""
    return out


def bridge_pids():
    """photocraft-cli processes running `mcp --bridge` (Claude Code may still hold one after removal)."""
    cli = CLI_NAME
    return [p for p, c in processes(cli) if re.search(r"\bmcp\b", c) and "--bridge" in c]


def kill(pid, force=True):
    if WIN:
        run(["taskkill", "/F", "/PID", str(pid)] if force else ["taskkill", "/PID", str(pid)])
    else:
        try:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        except OSError:
            pass


def _main_windows(pids):
    """Windows: top-level, visible, unowned windows of these processes."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.GetWindow.restype = wintypes.HWND
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _l):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and u.IsWindowVisible(h) and not u.GetWindow(h, 4):  # 4 = GW_OWNER
            found.append(h)
        return True

    u.EnumWindows(cb, 0)
    return u, found


def restore_gui(pids):
    """Un-minimize the control GUI so it draws (and can show a save prompt on close)."""
    if not pids:
        return
    if WIN:
        u, wins = _main_windows(set(pids))
        for h in wins:
            if u.IsIconic(h):
                u.ShowWindow(h, 9)  # SW_RESTORE
                say("gui: window was minimized; restored it")
                time.sleep(0.5)
    elif MAC:
        run(["osascript", "-e", 'tell application "System Events" to set visible of '
             '(every process whose unix id is ' + str(min(pids)) + ') to true'], timeout=10)


def close_gui(pids):
    """Ask the GUI to close like a window close, so it can ask about unsaved documents."""
    if WIN:
        import ctypes
        u, wins = _main_windows(set(pids))
        seen = set()
        for h in wins:  # the first top-level window of each process
            pid = ctypes.c_ulong()
            u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value not in seen:
                seen.add(pid.value)
                u.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE
    else:
        for p in pids:
            kill(p, force=False)


# ---------------------------------------------------------------- token and roots

def token_file(a):
    return a.TokenFile or os.environ.get("PHOTOCRAFT_CONTROL_TOKEN_FILE", "") or config_value("PHOTOCRAFT_TOKEN_FILE")


def check_token_file(path):
    """'' if usable, else the problem. A missing file is fine: PhotoCraft creates it."""
    if not path:
        return ("no token file: pass -TokenFile, set PHOTOCRAFT_CONTROL_TOKEN_FILE, or add "
                "PHOTOCRAFT_TOKEN_FILE=<file> to ~/.claude/photocraft/config.env")
    if os.path.isdir(path):
        return f"token file {path} is a folder"
    if not os.path.exists(path):
        parent = os.path.dirname(os.path.abspath(path))
        return "" if os.path.isdir(parent) else f"token file folder {parent} does not exist"
    try:
        with open(path, encoding="utf-8-sig") as fh:
            tok = fh.read().strip()
    except OSError as e:
        return f"token file {path} can't be read ({e.strerror})"
    return "" if TOKEN_RE.match(tok) else f"token file {path} does not hold a 64-hex-digit token"


def roots(a):
    rd = a.ReadRoot or config_values("PHOTOCRAFT_READ_ROOT")
    wr = a.WriteRoot or config_value("PHOTOCRAFT_WRITE_ROOT")
    return [os.path.abspath(r) for r in rd], (os.path.abspath(wr) if wr else "")


# ---------------------------------------------------------------- bridge

def bridge(cli, addr, tok):
    """Run the bridge for one initialize + one session_list call.
    Returns (stage, detail): ('ok', version), ('init', err), ('token', err) or ('call', err)."""
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "photocraft-mcp", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "session_list", "arguments": {}}},
    ]
    stdin = "".join(json.dumps(x) + "\n" for x in lines).encode()
    r = run([cli, "mcp", "--bridge", addr, "--control-token-file", tok], timeout=60, input=stdin)
    replies = {}
    for ln in text(r.stdout).splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict) and "id" in d:
            replies[d["id"]] = d
    err = scrub((text(r.stderr).strip().splitlines() or [""])[-1])
    init = replies.get(1, {})
    if "result" not in init:
        return "init", scrub(json.dumps(init.get("error"))) if init else (err or f"exit {r.returncode}")
    version = init["result"].get("serverInfo", {}).get("version", "?")
    call = replies.get(2, {})
    res = call.get("result") or {}
    body = "".join(c.get("text", "") for c in res.get("content", []) if isinstance(c, dict))
    if not call or "error" in call or res.get("isError"):
        detail = scrub(body or json.dumps(call.get("error")) if call else (err or "no reply"))
        return ("token" if TOKEN_MISMATCH in detail else "call"), detail[:300]
    return "ok", version


# ---------------------------------------------------------------- Claude Code registration

def claude_cmd():
    return shutil.which("claude")


def registration(claude):
    """(scope, command, args) of the current registration, or None. scope: local, user, project or ?."""
    r = run([claude, "mcp", "get", NAME])
    if r.returncode != 0:
        return None
    out = text(r.stdout)

    def field(name):
        m = re.search(rf"^\s*{name}:\s*(.*)$", out, re.M)
        return m.group(1).strip() if m else ""
    sc = field("Scope").lower()
    scope = next((s for s in ("local", "user", "project") if sc.startswith(s)), "?")
    return scope, field("Command"), field("Args")


def same_path(a, b):
    try:
        return norm(a) == norm(b)
    except (TypeError, ValueError):
        return False


def matches(reg, cli, addr, tok):
    """Is this registration `<cli> mcp --bridge <addr> --control-token-file <tok>`?"""
    if not reg or not same_path(reg[1], cli):
        return False
    m = re.match(r"^mcp --bridge (\S+) --control-token-file (.+)$", reg[2])
    return bool(m) and m.group(1) == addr and same_path(m.group(2).strip('"'), tok)


def register(a, cli, addr, tok):
    claude = claude_cmd()
    if not claude:
        say("ERROR: the claude command is not on PATH, so the MCP server can't be registered")
        return 6
    want = f"{cli} mcp --bridge {addr} --control-token-file {tok}"
    # `claude mcp get` shows one entry (local over project over user); walk down the scopes.
    for _ in range(4):
        reg = registration(claude)
        if matches(reg, cli, addr, tok):
            say(f"claude: MCP server '{NAME}' already registered ({reg[0]} scope)")
            return 0
        if reg and reg[0] not in ("local", "user"):
            say(f"ERROR: '{NAME}' is registered in the {reg[0]} scope (a project's .mcp.json?) as "
                f"'{scrub(reg[1] + ' ' + reg[2])}', not '{want}'; fix that entry (only if the user wants)")
            return 6
        if reg and reg[0] == "user" and a.Scope == "local":
            say(f"claude: the user-scope '{NAME}' is '{scrub(reg[1] + ' ' + reg[2])}'; adding a local one, "
                "which takes precedence here (the user entry is left as it is)")
            reg = None
        if not reg:
            run([claude, "mcp", "add", "-s", a.Scope, NAME, "--", cli, "mcp", "--bridge", addr,
                 "--control-token-file", tok])
            if not matches(registration(claude), cli, addr, tok):
                say("ERROR: 'claude mcp add' failed")
                return 6
            say(f"claude: registered MCP server '{NAME}' ({a.Scope} scope) -> {want}")
            return 0
        say(f"claude: '{NAME}' was '{scrub(reg[1] + ' ' + reg[2])}' ({reg[0]} scope); replacing it")
        if run([claude, "mcp", "remove", NAME, "-s", reg[0]]).returncode != 0:
            say(f"ERROR: could not remove the old '{NAME}' registration ({reg[0]} scope)")
            return 6
    say(f"ERROR: could not settle the '{NAME}' registration (claude mcp get {NAME})")
    return 6


# ---------------------------------------------------------------- actions

def report_roots(cmd, want_read, want_write):
    """Print the running GUI's roots; warn if the ones asked for aren't granted."""
    if not cmd:
        say("roots: unknown (could not read the running PhotoCraft's command line)")
        return
    have_r = [os.path.abspath(r) for r in flag_values(cmd, "--automation-read-root")]
    have_w = [os.path.abspath(w) for w in flag_values(cmd, "--automation-write-root")]
    say(f"roots: read={have_r or 'none'} write={have_w[-1] if have_w else 'none'}")
    missing = [r for r in want_read if norm(r) not in map(norm, have_r)]
    if want_write and norm(want_write) not in map(norm, have_w):
        missing.append(f"write {want_write}")
    if missing:
        say(f"WARN: the running PhotoCraft lacks root(s) {missing}; roots are set at launch, so 'stop' "
            "then 'start' to grant them")


def start(a, pcdir, cli, addr):
    tok = token_file(a)
    problem = check_token_file(tok)
    if problem:
        say(f"ERROR: {problem}")
        return 10
    tok = os.path.abspath(tok)
    want_read, want_write = roots(a)

    # 1. GUI with the control port
    if listening(a.Port):
        say(f"gui: control port {addr} already listening; reusing it")
        started = False
    else:
        gui = next((os.path.join(pcdir, g) for g in GUI_NAMES if os.path.isfile(os.path.join(pcdir, g))), "")
        if not gui:
            say(f"ERROR: no PhotoCraft app ({' or '.join(GUI_NAMES)}) next to {cli}. Pass -PhotoCraftDir.")
            return 9
        args = [gui, "--control", str(a.Port), "--control-token-file", tok]
        for r in want_read:
            args += ["--automation-read-root", r]
        if want_write:
            args += ["--automation-write-root", want_write]
        kw = {"cwd": pcdir, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if WIN:
            kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        env = {k: v for k, v in os.environ.items() if not k.startswith("PHOTOCRAFT_CONTROL_")}
        subprocess.Popen(args, env=env, **kw)
        deadline = time.time() + a.TimeoutSec
        while not listening(a.Port):
            if time.time() > deadline:
                say(f"ERROR: PhotoCraft did not open {addr} within {a.TimeoutSec} s (see {LOG_HINT})")
                return 3
            time.sleep(0.5)
        say(f"gui: started, control port listening on {addr}")
        started = True
    if check_token_file(tok):
        say(f"ERROR: {check_token_file(tok)}")
        return 10

    # 2. Bridge: initialize, then one real call that the app answers only for the right token.
    stage, detail = "call", ""
    deadline = time.time() + (a.TimeoutSec if started else 0)
    while True:
        stage, detail = bridge(cli, addr, tok)
        if stage in ("ok", "token", "init") or time.time() > deadline:
            break
        time.sleep(1)  # a fresh GUI may open the port before it can answer
    if stage == "init":
        say(f"ERROR: bridge initialize failed: {detail}")
        return 4
    if stage == "token":
        say(f"ERROR: {addr} is held by something that can't prove the token in {tok} (another app, or a "
            "PhotoCraft started with another token). Use another -Port, or close that PhotoCraft.")
        return 2
    if stage != "ok":
        say(f"ERROR: the bridge could not drive PhotoCraft: {detail}")
        return 5
    say(f"bridge: photocraft-cli mcp --bridge {addr} drove PhotoCraft {detail} (session_list OK)")
    guis = control_guis(a.Port)
    report_roots(next(iter(guis.values()), ""), want_read, want_write)

    # 3. Connect Claude Code (a stdio MCP server; Claude Code spawns the bridge itself)
    rc = register(a, cli, addr, tok)
    if rc:
        return rc
    say(f"READY gui={addr} mcp={NAME}")
    return 0


def stop(a):
    problems = 0
    # 1. Disconnect Claude Code from the local and user scopes (never a project's .mcp.json)
    claude = claude_cmd()
    removed = []
    if claude:
        for s in ("local", "user"):
            if run([claude, "mcp", "remove", NAME, "-s", s]).returncode == 0:
                removed.append(s)
    if removed:
        say(f"claude: removed MCP server '{NAME}' from scope(s): {', '.join(removed)}")
    elif claude:
        say(f"claude: MCP server '{NAME}' was not registered")
    else:
        say("claude: the claude command is not on PATH; registration not checked")
    if claude and registration(claude):
        say(f"WARN: '{NAME}' still registered (claude mcp get {NAME})")
        problems += 1

    # 2. Stop bridge processes
    bridges = bridge_pids()
    for b in bridges:
        kill(b)
    say(f"bridge: stopped {len(bridges)} photocraft-cli mcp process(es)" if bridges
        else "bridge: no photocraft-cli mcp --bridge process running")

    # 3. Close the control GUI gracefully; a PhotoCraft without --control is the user's and stays open.
    pids = list(control_guis(a.Port))
    others = [p for p in gui_pids() if p not in pids]
    if others:
        say(f"gui: leaving {len(others)} PhotoCraft window(s) without the control port open (pid "
            f"{','.join(map(str, others))})")
    if not pids:
        say(f"gui: no PhotoCraft serving port {a.Port}")
    else:
        restore_gui(pids)
        close_gui(pids)
        deadline = time.time() + a.TimeoutSec
        while any(p in gui_pids() for p in pids) and time.time() < deadline:
            time.sleep(0.5)
        left = [p for p in pids if p in gui_pids()]
        if not left:
            say("gui: PhotoCraft (control) closed")
        elif a.Force:
            for p in left:
                kill(p)
            say(f"gui: PhotoCraft did not close in {a.TimeoutSec} s; killed (-Force), unsaved work is lost")
        else:
            say(f"ERROR: PhotoCraft still running after {a.TimeoutSec} s (an unsaved-changes prompt or "
                "another dialog may be open). Ask the user, or re-run 'stop -Force'.")
            return 7
    if problems:
        return 8
    say("STOPPED")
    return 0


def status(a, cli, addr):
    tok = token_file(a)
    say(f"cli: {cli}")
    say(f"token file: {tok or 'not configured'}" + (f" ({check_token_file(tok)})" if check_token_file(tok) else ""))
    guis = control_guis(a.Port)
    say(f"gui: {'listening on ' + addr if listening(a.Port) else 'port ' + addr + ' closed'}; "
        f"control pid(s) {','.join(map(str, guis)) or 'none'}")
    if guis:
        report_roots(next(iter(guis.values())), *roots(a))
    claude = claude_cmd()
    reg = registration(claude) if claude else None
    say(f"claude: {NAME} " + (f"registered ({reg[0]} scope): {scrub(reg[1] + ' ' + reg[2])}" if reg
                              else "not registered"))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(prog="photocraft-mcp.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["start", "stop", "status"], type=str.lower)
    ap.add_argument("-Port", type=int, default=int(config_value("PHOTOCRAFT_PORT") or 7981))
    ap.add_argument("-TokenFile", default="")
    ap.add_argument("-ReadRoot", action="append", default=[])
    ap.add_argument("-WriteRoot", default="")
    ap.add_argument("-Scope", choices=["local", "user"], default="local", type=str.lower)
    ap.add_argument("-TimeoutSec", type=int, default=60)
    ap.add_argument("-Force", action="store_true")
    ap.add_argument("-PhotoCraftDir", default="")
    a = ap.parse_args(fix_argv(argv, ["-Port", "-TokenFile", "-ReadRoot", "-WriteRoot", "-Scope", "-TimeoutSec",
                                      "-PhotoCraftDir"], ["-Force"]))
    addr = f"127.0.0.1:{a.Port}"
    if a.action == "stop":
        return stop(a)
    pcdir = a.PhotoCraftDir or find()
    cli = os.path.join(pcdir, CLI_NAME) if pcdir else ""
    if not cli or not os.path.isfile(cli):
        say("ERROR: PhotoCraft not found. Pass -PhotoCraftDir or set PHOTOCRAFT_DIR (env or "
            "~/.claude/photocraft/config.env).")
        return 9
    if a.action == "status":
        return status(a, cli, addr)
    return start(a, pcdir, cli, addr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
