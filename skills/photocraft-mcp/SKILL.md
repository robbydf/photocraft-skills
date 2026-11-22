---
name: photocraft-mcp
description: Use when the user asks to start/launch or stop/shut down PhotoCraft (ArtCraft's pixel editor GUI, not headless) together with the PhotoCraft CLI MCP bridge, to connect or disconnect Claude Code from the PhotoCraft MCP server, to grant PhotoCraft automation read/write folders, or runs /photocraft-mcp start, stop or status. Also when photocraft-cli mcp --bridge or mcp__photocraft__* tools fail because nothing is listening on 127.0.0.1:7981 or the control token is rejected.
---

# photocraft-mcp

Three subcommands, all handled by the plugin's script. The argument after the skill name picks one
(`/photocraft-mcp start`, `/photocraft-mcp stop`, `/photocraft-mcp status`; installed as a plugin,
`/photocraft:photocraft-mcp start`). With no argument, run `status` and ask which.

The script is in the plugin's `scripts` folder, two levels above this skill's base directory
(`<base>/../../scripts/photocraft-mcp.py`). Use the real base directory you were given when this
skill loaded. From Bash or PowerShell (use `python3` on macOS and Linux if there is no `python`):

```bash
python "<base>/../../scripts/photocraft-mcp.py" start
python "<base>/../../scripts/photocraft-mcp.py" status
python "<base>/../../scripts/photocraft-mcp.py" stop
```

- **Install folder:** found by `find_photocraft.py`: `-PhotoCraftDir`, the `PHOTOCRAFT_DIR` environment
  variable, `PHOTOCRAFT_DIR=` in `~/.claude/photocraft/config.env`, then per system: the registry and
  `Program Files\ArtCraft\PhotoCraft` (Windows), `/Applications/PhotoCraft.app/Contents/MacOS` (macOS),
  `/opt/photocraft` and similar (Linux), and last `photocraft-cli` on `PATH`. That folder holds the GUI
  (`photocraft.exe`) and the CLI and bridge (`photocraft-cli.exe`).
- **Control address:** `127.0.0.1:7981` (`-Port`, or `PHOTOCRAFT_PORT=` in config.env). LightCraft uses
  7980, so both can run at once.
- **MCP server name in Claude Code:** `photocraft`.

## Token

PhotoCraft's control port requires a 64-hex-digit token, and the bridge refuses to start without one.
- The script uses a token **file**: `-TokenFile`, else `$PHOTOCRAFT_CONTROL_TOKEN_FILE`, else
  `PHOTOCRAFT_TOKEN_FILE=` in `~/.claude/photocraft/config.env`. If none is set, ask the user for the
  file and save it there. If the file doesn't exist yet, PhotoCraft creates it on start.
- The GUI starts with `--control-token-file <file>`, and Claude Code's registration passes the same
  path (`--control-token-file`), so the token itself is never in a command line or a config.
- **Never print, echo or `cat` the token**, and never put it in a commit, a log, or a message. To check
  a file, use the script's `status` (it reports only whether the file holds a valid token).
- `%APPDATA%\PhotoCraft\instance.json` also holds a token (the single-instance one). Don't read it.

## Automation roots

MCP file tools (`doc_open`, `doc_save`, `doc_place`, exports) can reach only the folders granted when the
GUI starts. Relative paths resolve against them (`doc_save path=t.png` writes into the write root).
- `-ReadRoot <dir>` (repeat for more; else every `PHOTOCRAFT_READ_ROOT=` line in config.env) and
  `-WriteRoot <dir>` (one; else `PHOTOCRAFT_WRITE_ROOT=`).
- Without any root the bridge still drives the GUI (documents already open, UI, history), but it can't
  open or save files.
- Roots can't change on a running PhotoCraft. When `start` reuses one that lacks a requested root, it
  prints `WARN: the running PhotoCraft lacks root(s) …`. Tell the user; `stop` then `start` with the
  roots closes their PhotoCraft window, so do that only on their yes.
- Grant the narrowest folders the task needs (the photo's folder, an output folder), not a drive root.
- The write root isn't readable unless it is also a read root. Add it as one when a task reopens
  what it saved.

## start

1. Checks the token file (exit 10 if unusable).
2. Starts the GUI with `--control 7981 --control-token-file <file>` and the roots, or reuses whatever
   already listens on the port. A PhotoCraft the user opened normally (no `--control`) doesn't block
   this: PhotoCraft runs the control instance as a separate process.
3. Drives it through the bridge: an MCP `initialize`, then a `session_list` call. Only the app holding
   the same token answers that call, so this also proves the token.
4. Prints the running instance's roots (`roots: read=[…] write=…`).
5. Connects Claude Code if the server isn't registered yet:
   `claude mcp add -s local photocraft -- "<cli>" mcp --bridge 127.0.0.1:7981 --control-token-file "<file>"`.
   Claude Code spawns the bridge itself (stdio), so nothing is left running for it.

Options: `-Scope user` (register for every project instead of only the current folder), `-Port`,
`-TokenFile`, `-ReadRoot`, `-WriteRoot`, `-TimeoutSec` (default 60), `-PhotoCraftDir`.

Success ends with `READY`. A fresh start takes about 30 s. The `mcp__photocraft__*` tools appear after
Claude Code (re)connects. If they are missing in the current session, tell the user to start a new
session (or run `/mcp`). Until then you can drive the same bridge from Bash by piping JSON-RPC lines
into `photocraft-cli mcp --bridge 7981 --control-token-file <file>`.

## status

Read-only: the CLI path, whether the token file is usable, whether the port listens and which PhotoCraft
pid holds it, its roots, and the Claude Code registration. Run it first when something fails.

## stop

1. Disconnects Claude Code: `claude mcp remove photocraft` from the local and user scopes. A
   project's own `.mcp.json` is left alone.
2. Stops any running `photocraft-cli mcp --bridge` processes.
3. Closes only the PhotoCraft started with `--control` on this port, with a window close, so it can
   ask about unsaved documents. Other PhotoCraft windows stay open. Waits up to `-TimeoutSec`.

Success ends with `STOPPED`. `-Force` kills PhotoCraft if it won't close, losing unsaved work; use it
only when the user says so.

## Exit codes

| Exit | Meaning | What to do |
|------|---------|------------|
| 2 | start: the port is held by something that can't prove the token (another app, or a PhotoCraft started with a different token file) | Tell the user. Offer another `-Port`, or closing that PhotoCraft. Never kill it unasked. |
| 3 | start: the control port never opened | Check `%APPDATA%\PhotoCraft\logs\photocraft.log` (`~/Library/Application Support/PhotoCraft/logs/` on macOS, `~/.local/share/PhotoCraft/logs/` on Linux). |
| 4 / 5 | start: the bridge initialize failed / the bridge couldn't drive the GUI | Show the error line; run `status`. |
| 6 | start: `claude mcp add` failed, `claude` isn't on PATH, or a project `.mcp.json` registers `photocraft` differently | Show the error line. A local or user registration pointing elsewhere (another port, token file or install) is replaced automatically; a `.mcp.json` entry is the user's to change. |
| 7 | stop: the GUI is still open (an unsaved-changes prompt?) | Ask the user to answer it, or re-run `stop -Force` only on their yes. |
| 8 | stop: the registration is still present | Usually a project's own `.mcp.json`. Run `claude mcp get photocraft` to see the scope. |
| 9 | PhotoCraft not found | Ask for the install folder and save it as `PHOTOCRAFT_DIR=<folder>` in `~/.claude/photocraft/config.env`. |
| 10 | no usable token file | Ask the user for the file and save it as `PHOTOCRAFT_TOKEN_FILE=<file>` in config.env. |

## Using the tools (PhotoCraft 0.23.1, bridge mode)

Start with `doc_open` / `doc_new`, list command ids and their parameters with `command_list`, edit with
`command_run` or `command_batch` (one history step per command), check with `doc_inspect` and
`render_preview` (in bridge mode that is a window screenshot), and write with `doc_save`. `ui_*` tools work
only in bridge mode, which this skill sets up. Tested November 2026 (GoPro JPEGs and a 144 MB 16-bit
LightCraft `-Edit.psd`):

**Opening**
- `doc_open path=…` takes a path relative to the read roots (forward slashes, searched in launch order;
  `sub/x.jpg` works) or an absolute path inside one (backslashes or forward slashes).
- Refused: an absolute path outside every read root, and any `..` ("parent traversal is not allowed").
- Opening the same file twice opens a second tab. Check `session_list` → `session.documents` first.
- The 144 MB PSD opened in about a second. Opening never changes the file.

**Switching documents.** `doc_select` is headless-only. In the GUI, switch with
`ui_menu_invoke id=window.document.<index>` (the index from `session_list`), which returns
`{"document": <index>}`. Every save, edit and inspect acts on the **active** document, so switch first.

**Saving**
- `doc_save path=…` writes the active document. Relative paths go into the write root; an absolute path
  must be inside it. A read root that isn't the write root is refused, so is `..`.
- Bridge mode refuses `index`, `quality`, `format` and the other export options ("bridge mode saves with
  the app's current settings"). The extension picks the format: `.pcraft` (native, lossless), `.psd`,
  `.png`, `.jpg`, `.tif`, `.webp` all worked. The result's `warnings` say what the format lost (`16-bit
  will be reduced to 8-bit`, `lossy compression`).
- A subfolder of the write root must already exist (`sub/new/x.png` fails with NotFound).
- An existing file is overwritten without asking.
- `doc_save` with a path is **Save As**: the document now points at the new file, and a later `doc_save`
  without a path writes there (only for `.psd`, `.psb` and `.pcraft`). A document opened through
  automation has `path: null` until then, so `doc_save` without a path can't write back to the original.
- Sizes for a 24 MP 16-bit image: `.psd` 289 MB, `.pcraft` 189 MB, `.tif` 144 MB, `.png` 125 MB,
  `.webp` 35 MB, `.jpg` 5.6 MB. A full-size save can take tens of seconds.
- Files written to the write root can't be reopened unless that folder is also a read root. Grant it as
  both when a task saves and then reopens.

**Closing**
- `doc_close` is headless-only. In the GUI use `ui_menu_invoke id=file.close` on the active document.
- A clean document closes at once. A modified one opens an `unsavedChanges` dialog (in `session_list` →
  `dialogs`, id `discard`, choices `save`, `dontSave`, `cancel`) and stays open. Answer it with
  `control_call method=ui.dialog.confirm params={"dialog":"discard","choice":"dontSave"}`. Only choose
  `dontSave` for documents you created or the user said to discard; otherwise ask.

**Order.** Requests sent together in one bridge session can finish out of order (a save ran before the
`doc_new` it needed). Wait for each reply before sending a call that depends on it.

## Common mistakes

- `photocraft-cli mcp` **without** `--bridge` starts a separate headless engine, not the GUI.
- The bridge refuses root flags (`--automation-read-root`): roots belong on the GUI, at start.
- `claude mcp get photocraft` exiting 1 with `No MCP server named "photocraft"` just means it isn't
  registered.
- `stop` closes the control PhotoCraft window and any open documents: only run it when the user asked.
