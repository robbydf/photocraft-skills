"""Print the folder that holds PhotoCraft's CLI (photocraft-cli.exe on Windows, photocraft-cli elsewhere).

Order: --dir argument (if given, the only folder searched, up to two levels deep), $PHOTOCRAFT_DIR, PHOTOCRAFT_DIR in <PHOTOCRAFT_HOME>/config.env, then per system:
  Windows: the uninstall entries in the registry, then Program Files / Program Files (x86) /
           %LOCALAPPDATA%\\Programs (ArtCraft\\PhotoCraft or PhotoCraft)
  macOS:   /Applications and ~/Applications: PhotoCraft.app, ArtCraft/PhotoCraft.app (Contents/MacOS)
  Linux:   /opt/photocraft, /opt/PhotoCraft, /opt/ArtCraft/PhotoCraft, /usr/lib/photocraft,
           ~/.local/share/photocraft, ~/.local/opt/photocraft
  last:    photocraft-cli on PATH
PHOTOCRAFT_HOME defaults to ~/.claude/photocraft.
Exit 1 (and print nothing) if none is found, 2 on a usage error. Standard library only.
Usage: python find_photocraft.py [--dir <folder>] | --help
"""
import glob
import os
import re
import shutil
import sys

WIN = os.name == "nt"
MAC = sys.platform == "darwin"
CLI_NAME = "photocraft-cli.exe" if WIN else "photocraft-cli"
NAME_RE = re.compile(r"PhotoCraft|ArtCraft", re.I)


def has_cli(d):
    return bool(d) and os.path.isfile(os.path.join(d, CLI_NAME))


def pc_home():
    h = os.environ.get("PHOTOCRAFT_HOME")
    return h if h else os.path.join(os.path.expanduser("~"), ".claude", "photocraft")


def config_values(key):
    """Every value of KEY=value in <PHOTOCRAFT_HOME>/config.env, in file order (quotes stripped).
    A ` # comment` after an unquoted value is dropped."""
    cfg = os.path.join(pc_home(), "config.env")
    out = []
    # A value with only an opening quote (KEY="D:/t.txt) still counts, as it always did.
    pat = re.compile(r'^\s*' + re.escape(key) + r'\s*=\s*(?:"([^"]*)"|"?([^"]*?))\s*(?:\s#.*)?$')
    try:
        with open(cfg, encoding="utf-8-sig") as fh:
            for line in fh:
                m = pat.match(line.rstrip("\r\n"))
                if m:
                    v = m.group(1) if m.group(1) is not None else m.group(2)
                    if v:
                        out.append(v)
    except OSError:
        pass
    return out


def config_value(key):
    """The last KEY=value in config.env, or ''."""
    v = config_values(key)
    return v[-1] if v else ""


def windows_candidates():
    out = []
    try:
        import winreg
    except ImportError:
        return out
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in roots:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        def val(n):
                            try:
                                return str(winreg.QueryValueEx(k, n)[0])
                            except OSError:
                                return ""
                        if NAME_RE.search(val("DisplayName")):
                            loc = val("InstallLocation")
                            if loc:
                                # An ArtCraft entry may point at the suite folder: try its PhotoCraft too.
                                out += [loc, os.path.join(loc, "PhotoCraft")]
                            icon = re.sub(r'"|,\d+$', "", val("DisplayIcon"))
                            if icon:
                                out.append(os.path.dirname(icon))
                except OSError:
                    continue
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(var):
            out += [os.path.join(os.environ[var], "ArtCraft", "PhotoCraft"), os.path.join(os.environ[var], "PhotoCraft")]
    if os.environ.get("LOCALAPPDATA"):
        p = os.path.join(os.environ["LOCALAPPDATA"], "Programs")
        out += [os.path.join(p, "ArtCraft", "PhotoCraft"), os.path.join(p, "PhotoCraft")]
    return out


def mac_candidates():
    out = []
    for apps in ("/Applications", os.path.expanduser("~/Applications")):
        for app in ("PhotoCraft.app", "ArtCraft/PhotoCraft.app", "ArtCraft PhotoCraft.app"):
            out.append(os.path.join(apps, app, "Contents", "MacOS"))
        out += [os.path.join(p, "Contents", "MacOS") for p in sorted(glob.glob(os.path.join(apps, "*PhotoCraft*.app")))]
    return out


def linux_candidates():
    home = os.path.expanduser("~")
    return ["/opt/photocraft", "/opt/PhotoCraft", "/opt/ArtCraft/PhotoCraft", "/usr/lib/photocraft",
            os.path.join(home, ".local", "share", "photocraft"), os.path.join(home, ".local", "opt", "photocraft")]


def candidates(arg):
    c = [arg, os.environ.get("PHOTOCRAFT_DIR", ""), config_value("PHOTOCRAFT_DIR")]
    if WIN:
        c += windows_candidates()
    elif MAC:
        c += mac_candidates()
    else:
        c += linux_candidates()
    on_path = shutil.which(CLI_NAME)
    if on_path:
        c.append(os.path.dirname(os.path.realpath(on_path)))
    return [x for x in c if x]


def search(c, deep=False):
    """The folder holding the CLI: c itself, or up to two levels below it. The deeper search runs only
    inside a PhotoCraft folder (never a drive root or Program Files), or anywhere when deep=True (a
    folder the user named, such as an ArtCraft suite folder or PhotoCraft.app)."""
    if has_cli(c):
        return os.path.abspath(c)
    if os.path.isdir(c) and (deep or re.search("PhotoCraft", os.path.basename(os.path.normpath(c)), re.I)):
        base = os.path.normpath(c).count(os.sep)
        for root, dirs, fs in os.walk(c):
            if CLI_NAME in fs:
                return os.path.abspath(root)
            if root.count(os.sep) - base >= 2:
                dirs[:] = []
    return ""


def find(arg=""):
    """An explicit folder (arg) is the only place searched; otherwise the usual order."""
    if arg:
        return search(arg, deep=True)
    for c in candidates(""):
        d = search(c)
        if d:
            return d
    return ""


def main(argv):
    arg = ""
    if argv and argv[0].lower() in ("-h", "--help", "-help", "/?"):
        print(__doc__)
        return
    if len(argv) == 2 and argv[0].lower() in ("--dir", "-dir"):
        arg = argv[1]
    elif argv:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    d = find(arg)
    if not d:
        sys.exit(1)
    print(d)


if __name__ == "__main__":
    main(sys.argv[1:])
