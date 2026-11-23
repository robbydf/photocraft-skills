#!/usr/bin/env python3
"""Drive a running control PhotoCraft through the bridge, one MCP tool call after another.

    python pc-bridge.py calls.json [-Port 7981] [-TokenFile FILE] [-OutDir DIR] [-PhotoCraftDir DIR]

calls.json is a JSON list of [tool, arguments] pairs, for example
    [["doc_open", {"path": "x-Edit.psd"}], ["ui_screenshot", {}]]

Use it when the mcp__photocraft__* tools aren't loaded in the session. Each call waits for its reply
before the next one is sent (calls sent together can finish out of order). Text results are printed
(with any 64-hex token scrubbed), images are saved as PNG files in -OutDir (default: the calls file's
folder) and their paths printed. Stops at the first error. Exit 0 when every call succeeded, 1 on a
tool error, 10 when there is no usable token file, 9 when PhotoCraft isn't found, 11 on a usage error.
"""
import base64
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from find_photocraft import CLI_NAME, config_value, find  # noqa: E402
from pcargs import fix_argv  # noqa: E402

HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")


def scrub(s):
    return HEX64.sub("<token>", s)


def load_calls(path):
    """Read and check the calls file: a list of [tool name, arguments object] pairs."""
    with open(path, encoding="utf-8-sig") as f:
        calls = json.load(f)
    if not isinstance(calls, list):
        raise ValueError("the calls file must hold a JSON list of [tool, arguments] pairs")
    out = []
    for i, c in enumerate(calls):
        if (not isinstance(c, list) or len(c) not in (1, 2) or not isinstance(c[0], str)
                or (len(c) == 2 and not isinstance(c[1], dict))):
            raise ValueError("call %d is not [tool, {arguments}]" % i)
        out.append((c[0], c[1] if len(c) == 2 else {}))
    return out


def parse(argv):
    import argparse
    p = argparse.ArgumentParser(prog="pc-bridge.py")
    p.add_argument("calls")
    p.add_argument("-Port", type=int, default=0)
    p.add_argument("-TokenFile", default="")
    p.add_argument("-OutDir", default="")
    p.add_argument("-PhotoCraftDir", default="")
    return p.parse_args(fix_argv(argv, ["-Port", "-TokenFile", "-OutDir", "-PhotoCraftDir"]))


def main(argv):
    try:
        a = parse(argv)
    except SystemExit:
        return 11
    try:
        calls = load_calls(a.calls)
    except (OSError, ValueError) as e:
        print("ERROR: %s" % e)
        return 11
    port = a.Port or int(config_value("PHOTOCRAFT_PORT") or 7981)
    tok = (a.TokenFile or os.environ.get("PHOTOCRAFT_CONTROL_TOKEN_FILE", "")
           or config_value("PHOTOCRAFT_TOKEN_FILE"))
    if not tok or HEX64.fullmatch(tok.strip()) or not os.path.isfile(tok):
        print("ERROR: no usable token file (pass -TokenFile or set PHOTOCRAFT_TOKEN_FILE in config.env)")
        return 10
    pcdir = find(a.PhotoCraftDir)
    if not pcdir:
        print("ERROR: PhotoCraft not found")
        return 9
    outdir = a.OutDir or os.path.dirname(os.path.abspath(a.calls))
    cli = os.path.join(pcdir, CLI_NAME)
    p = subprocess.Popen([cli, "mcp", "--bridge", "127.0.0.1:%d" % port, "--control-token-file", tok],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    nid = [0]

    def rpc(method, params, notify=False):
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            nid[0] += 1
            msg["id"] = nid[0]
        p.stdin.write(json.dumps(msg) + "\n")
        p.stdin.flush()
        if notify:
            return None
        while True:
            line = p.stdout.readline()
            if not line:
                raise RuntimeError("the bridge closed (is the control PhotoCraft running? run "
                                   "photocraft-mcp.py status)")
            r = json.loads(line)
            if r.get("id") == nid[0]:
                return r

    rc = 0
    try:
        rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "pc-bridge.py", "version": "1"}})
        rpc("notifications/initialized", {}, notify=True)
        for i, (name, args) in enumerate(calls):
            r = rpc("tools/call", {"name": name, "arguments": args})
            print("== %d %s" % (i, name))
            if "error" in r:
                print(scrub("ERROR: " + json.dumps(r["error"])))
                rc = 1
                break
            res = r.get("result", {})
            for c in res.get("content", []):
                if c.get("type") == "text":
                    print(scrub(c["text"]))
                elif c.get("type") == "image":
                    fn = os.path.join(outdir, "pc-bridge-%d-%s.png" % (i, name))
                    with open(fn, "wb") as f:
                        f.write(base64.b64decode(c["data"]))
                    print("image: %s" % fn)
            if res.get("isError"):
                print("ERROR: the tool reported an error")
                rc = 1
                break
    except RuntimeError as e:
        print("ERROR: %s" % e)
        rc = 1
    finally:
        try:
            p.stdin.close()
            p.wait(timeout=30)
        except Exception:
            p.kill()
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
