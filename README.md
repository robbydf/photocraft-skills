# photocraft-skills

A Claude Code plugin for **PhotoCraft**, ArtCraft's layered pixel editor. Claude drives the PhotoCraft
GUI through its token-protected control port and the `photocraft-cli` MCP bridge. It is the companion of
[lightcraft-skills](https://github.com/robbydf/lightcraft-skills): LightCraft develops and culls the
photos, and PhotoCraft does the pixel work LightCraft can't.

| Skill | What it does |
|---|---|
| `photocraft-mcp` | `start`: launch PhotoCraft with its control port, token file and automation folders, prove the bridge can drive it, and register the `photocraft` MCP server with Claude Code. `status`: show what's running and registered. `stop`: disconnect and close the control PhotoCraft gracefully. |

Planned next: a skill that removes strangers and bystanders from photos handed over from LightCraft.

## Install

```
/plugin install photocraft --marketplace robbydf/photocraft-skills
```

Or add the marketplace first, then install from it:

```
/plugin marketplace add robbydf/photocraft-skills
/plugin install photocraft@photocraft-skills
```

Then, in Claude Code, run `/photocraft:photocraft-mcp start` (plugin skills are namespaced), or just ask
Claude to start PhotoCraft. Set the token file first (see Configuration).

## Requirements

- **Windows, macOS or Linux.** The helpers are Python. Tested on Windows 11; on macOS and Linux the
  install-folder detection and the GUI start/stop use best-guess paths, so set `PHOTOCRAFT_DIR` if
  PhotoCraft isn't found.
- **PhotoCraft**, tested on **0.23.1**.
- **Python 3.8+** (`python`, or `python3` where there is no `python`). Standard library only.

## Configuration

Everything personal lives outside the plugin, in `~/.claude/photocraft/` (or `$PHOTOCRAFT_HOME`).
`config.env` holds `KEY=value` lines:

| Key | Purpose |
|---|---|
| `PHOTOCRAFT_TOKEN_FILE` | **Required.** The file holding the control token (64 hex digits). PhotoCraft creates it if it's missing. `-TokenFile` or `$PHOTOCRAFT_CONTROL_TOKEN_FILE` override it. |
| `PHOTOCRAFT_READ_ROOT` | A folder MCP tools may read from. Repeat the line for more. `-ReadRoot` overrides. |
| `PHOTOCRAFT_WRITE_ROOT` | The one folder MCP tools may write to. `-WriteRoot` overrides. |
| `PHOTOCRAFT_PORT` | The control port (default 7981; LightCraft's default is 7980). |
| `PHOTOCRAFT_DIR` | The install folder, if detection doesn't find it. |

Example:

```
PHOTOCRAFT_TOKEN_FILE=D:/Secrets/photocraft-token.txt
PHOTOCRAFT_READ_ROOT=E:/Photos
PHOTOCRAFT_WRITE_ROOT=E:/Photos/PhotoCraft
```

**Token:** the token never leaves its file. The GUI gets `--control-token-file <file>`, and Claude Code's
registration passes the same path to the bridge, so the token is in no command line, no Claude Code
config and no log. Never commit the token file (`.gitignore` covers `token.txt` and `*.token`).

**Automation roots** are fixed when PhotoCraft starts. To change them, `stop` and `start` again.

**Install folder detection,** in this order (`scripts/find_photocraft.py`):
1. `--dir` to `find_photocraft.py`, `-PhotoCraftDir` to `photocraft-mcp.py`;
2. the `PHOTOCRAFT_DIR` environment variable;
3. `PHOTOCRAFT_DIR` in `config.env`;
4. per system: Windows, the uninstall entries in the registry, then `ArtCraft\PhotoCraft` or
   `PhotoCraft` in `Program Files`, `Program Files (x86)` and `%LOCALAPPDATA%\Programs`; macOS,
   `PhotoCraft.app` (or `ArtCraft/PhotoCraft.app`, `*PhotoCraft*.app`) in `/Applications` or
   `~/Applications`; Linux, `/opt/photocraft`, `/opt/PhotoCraft`, `/opt/ArtCraft/PhotoCraft`,
   `/usr/lib/photocraft`, `~/.local/share/photocraft`, `~/.local/opt/photocraft`;
5. last, the folder of `photocraft-cli` on `PATH`.

## Layout

```
.claude-plugin/plugin.json        plugin manifest
.claude-plugin/marketplace.json   lets this repo be added as a marketplace
skills/photocraft-mcp/SKILL.md
scripts/
  find_photocraft.py    install folder detection (Windows, macOS, Linux) and config.env reading
  photocraft-mcp.py     start / status / stop
  pcargs.py             PowerShell-style options (-Port 7981, -ReadRoot DIR)
tests/test_scripts.py
```

Tests (no PhotoCraft needed): `python -E -m unittest discover -s tests -v` from the repo root
(`python3` on macOS and Linux). GitHub Actions runs them on Windows, macOS and Linux.

## Safety

- The token is never printed: the scripts replace any 64-hex string in their output with `<token>`.
- `stop` closes only the PhotoCraft started with `--control` on the port, with a normal window close, so
  PhotoCraft can ask about unsaved documents. A PhotoCraft you opened yourself stays open. `-Force`
  kills it and is only for when you say so.
- `start` never kills anything. If the port is held by something that can't prove the token, it stops
  and says so.

## Known behaviour, PhotoCraft 0.23.1

- The bridge needs a token: `photocraft-cli mcp --bridge` refuses to start without one, and the app
  rejects a call (not the `initialize`) when the token doesn't match.
- A PhotoCraft started with `--control` runs as its own process, next to one you opened normally.
- `photocraft-cli mcp` without `--bridge` starts a separate headless engine, not the GUI.
- `doc_select` and `doc_close` are headless-only. In the GUI, switch with `ui_menu_invoke
  window.document.<index>` and close with `ui_menu_invoke file.close`. Saves act on the active document.
- In bridge mode `doc_save` takes only a path: the extension picks the format, and quality and format
  options are refused. It overwrites without asking, and doesn't create subfolders.
- `doc_save` with a path is Save As: the document then points at the new file.
- Closing a modified document opens an unsaved-changes dialog, answered with `control_call
  ui.dialog.confirm`.
- Requests sent together in one bridge session can complete out of order.
- The skill's "Using the tools" section has the details.
- A fresh start takes about 30 s before the bridge can drive the GUI.

## License

MIT. See [LICENSE](LICENSE).
