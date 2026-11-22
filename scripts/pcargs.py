"""Option handling shared by the helper scripts (standard library only), as in lightcraft-skills.

The helpers keep the option style of the PowerShell scripts they replace, so existing commands keep
working: `-Region 0.1,0.9,0,1`, `-Out x.png`, `-Angles -6,-4,-2,0,2,4,6`. Option names are
case-insensitive (`-region` works too), and a value that starts with '-' is taken as the value, not
as another option, which plain argparse refuses.
"""
import sys

# Print LF, not CRLF, on Windows too, so output compares equal across systems and in Git Bash.
try:
    sys.stdout.reconfigure(newline="\n")
except (AttributeError, ValueError):
    pass


def fix_argv(argv, options, switches=()):
    """Rewrite argv for argparse: `-name value` -> `-Name=value` for the options that take a value,
    and `-name` -> `-Name` for switches. Everything else passes through unchanged."""
    canon = {o.lower(): o for o in options}
    sw = {s.lower(): s for s in switches}
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("-") and len(a) > 1 and not a[1].isdigit() and a[1] != ".":
            name, eq, val = a.partition("=")
            key = name.lower()
            if key in canon:
                if eq:
                    out.append(f"{canon[key]}={val}")
                elif i + 1 < len(argv):
                    out.append(f"{canon[key]}={argv[i + 1]}")
                    i += 1
                else:
                    out.append(canon[key])          # argparse reports the missing value
                i += 1
                continue
            if key in sw and not eq:
                out.append(sw[key])
                i += 1
                continue
        out.append(a)
        i += 1
    return out
