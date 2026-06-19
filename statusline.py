#!/usr/bin/env python3
"""
Claude Code statusline — Tokyo Night powerline edition.
https://github.com/NeverGET/claude-code-tokyonight-statusline

Line 1 (top, ░▒▓ lead) — workspace + all info chips:
    ░▒▓  path    git    5h/7d    effort    $cost    clock    session    ╶ last prompt (dim)
Line 2 (bottom,  rounded pill, offset by spaces) — model + FULL-WIDTH context gauge:
      󰚩 model    NN% · used/limit   ████████████████████░░░░░░░░░ (fills terminal width)

Requires: Python 3.8+ and a Nerd Font (e.g. MesloLGS NF, FiraCode NF, JetBrainsMono NF)
selected in your terminal — the icons and powerline separators are Nerd Font glyphs.
Reads the native Claude Code statusline JSON (Claude Code v2.1.132+; live width via
COLUMNS needs v2.1.153+). Cross-platform: Linux, macOS, Windows. Pure stdlib, no deps.
Never crashes (a crash = blank statusline), guarded everywhere. MIT licensed.
"""
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime

# ── Tokyo Night palette (Starship "tokyo-night" preset colors + standard accents) ──
LAV     = (163, 174, 210)  # #a3aed2  lavender lead / model fg
BLUE    = (118, 159, 240)  # #769ff0  directory bg / accent fg
NAVY    = (57, 66, 96)     # #394260  git / model bg
SLATE   = (33, 39, 54)     # #212736  context bg / chip bg A
DARK    = (29, 34, 48)     # #1d2230  chip bg B
DIRFG   = (227, 229, 229)  # #e3e5e5  directory text
TIMEFG  = (160, 169, 203)  # #a0a9cb  muted chip text
GREEN   = (158, 206, 106)  # #9ece6a
YELLOW  = (224, 175, 104)  # #e0af68
ORANGE  = (255, 158, 100)  # #ff9e64
RED     = (247, 118, 142)  # #f7768e
MAGENTA = (187, 154, 247)  # #bb9af7  compaction-point marker
EMPTY   = (70, 80, 100)    # dim fill for the empty part of the wide bar
DIM     = (90, 100, 120)   # last-prompt tail

# ── Nerd Font glyphs (require any Nerd Font; codepoints from the core NF ranges) ──
FOLDER  = chr(0xEA83)   #   cod-folder
HOME    = chr(0xF015)   #   fa-home
BRANCH  = chr(0xF418)   #   oct-git_branch
DIRTY   = chr(0xEA71)   #   cod-circle_filled
AHEAD   = chr(0xF062)   #   fa-arrow_up
BEHIND  = chr(0xF063)   #   fa-arrow_down
ROBOT   = chr(0xF06A9)  # 󰚩  md-robot
WARN    = chr(0xF071)   #   fa-warning (>200k tier)
BOLT    = chr(0xF0E7)   #   fa-bolt (effort)
DOLLAR  = chr(0xF155)   #   fa-dollar
CLOCK   = chr(0xF43A)   #   oct-clock
FINGER  = chr(0xF0237)  # 󰈷  md-fingerprint
SEP     = chr(0xE0B4)   #   right half-circle (chain separator / right cap)
CAPL    = chr(0xE0B6)   #   left half-circle (left round cap — reverse of SEP)
LEAD    = "░▒▓"          # standard Unicode fade-in (line 1 only)

# ── ANSI helpers (24-bit truecolor) ──
RESET = "\033[0m"
def fg(c): return f"\033[38;2;{c[0]};{c[1]};{c[2]}m"
def bg(c): return f"\033[48;2;{c[0]};{c[1]};{c[2]}m"
_ANSI = re.compile(r"\033\[[0-9;]*m")
def vis(s): return _ANSI.sub("", s)
def vlen(s): return len(vis(s))


def _cw(ch):
    """Display width of one char. SPUA-A/B nerd glyphs (md-robot, md-fingerprint,
    U+F0000+) and East-Asian wide/fullwidth render as 2 cells in the terminal."""
    o = ord(ch)
    if o >= 0xF0000:
        return 2
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1
def dwidth(s):
    """True on-screen cell width of a string (ANSI stripped, wide glyphs = 2)."""
    return sum(_cw(c) for c in vis(s))


def chain(segments):
    """Line-1 builder: ░▒▓ lead + rounded powerline chain.
    segments: list of (text, fgcolor, bgcolor)."""
    if not segments:
        return ""
    out = fg(LAV) + LEAD
    out += fg(LAV) + bg(segments[0][2]) + SEP          # lavender cap into first seg
    for i, (text, f, b) in enumerate(segments):
        out += fg(f) + bg(b) + text
        if i + 1 < len(segments):
            out += fg(b) + bg(segments[i + 1][2]) + SEP
        else:
            out += RESET + fg(b) + SEP + RESET
    return out


# ── Data helpers ──
def humanize(tokens):
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.2f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.0f}k"
    return str(tokens)


def dotted(n):
    """Raw integer with '.' thousands separators (e.g. 117564 -> '117.564')."""
    return f"{int(n):,}".replace(",", ".")


_WIDTH_SRC = "?"
def term_width():
    """Robust terminal width: COLUMNS env -> /dev/tty ioctl -> get_terminal_size -> fallback.
    The ioctl path works in Claude Code's statusline subprocess (it has a controlling
    tty) even though stdout is captured, so width tracks live terminal resizing."""
    global _WIDTH_SRC
    try:
        c = int(os.environ.get("COLUMNS", "0"))
        if c > 0:
            _WIDTH_SRC = "COLUMNS"
            return c
    except ValueError:
        pass
    try:
        import fcntl, termios, struct
        with open("/dev/tty") as t:
            _, w, _, _ = struct.unpack("HHHH", fcntl.ioctl(t, termios.TIOCGWINSZ, b"\0" * 8))
            if w > 0:
                _WIDTH_SRC = "tty"
                return w
    except Exception:
        pass
    for fd in (2, 1, 0):
        try:
            w = os.get_terminal_size(fd).columns
            if w > 0:
                _WIDTH_SRC = f"fd{fd}"
                return w
        except Exception:
            pass
    _WIDTH_SRC = "fallback"
    return 100


def gauge_color(pct):
    """For rate-limit chips: utilization where higher is always worse."""
    if pct < 60:  return GREEN
    if pct < 80:  return YELLOW
    if pct < 90:  return ORANGE
    return RED


def compaction_frac(limit):
    """Where Claude Code auto-compacts, as a fraction of the limit:
    ~78% for the 200k window, ~85% (~850k) for the 1M window."""
    return 0.85 if limit >= 1_000_000 else 0.78


def bar_color(pct, limit):
    """Context-bar color RELATIVE to the compaction point:
    green (safe) -> orange (within ~10% of limit below compaction) -> red (at/past)."""
    comp = compaction_frac(limit) * 100
    if pct >= comp:
        return RED
    if pct >= comp - 10:
        return ORANGE
    return GREEN


def wide_bar(pct, cells, comp_frac, col):
    """Full-width gauge scaled to the TRUE limit, with a magenta compaction marker
    at the auto-compact point (which is also where the bar turns red)."""
    cells = max(8, cells)
    filled = int(round(pct / 100.0 * cells))
    comp = int(round(comp_frac * cells))
    out = ""
    for i in range(cells):
        if i == comp:
            out += fg(MAGENTA) + ("█" if i < filled else "│")
        elif i < filled:
            out += fg(col) + "█"
        else:
            out += fg(EMPTY) + "░"
    return out


def git_segment(cwd):
    def run(args):
        return subprocess.run(["git", "-C", cwd] + args,
                              capture_output=True, text=True, timeout=0.5)
    try:
        r = run(["rev-parse", "--abbrev-ref", "HEAD"])
        if r.returncode != 0:
            return None
        branch = r.stdout.strip() or "HEAD"
        parts = f" {BRANCH} {branch}"
        st = run(["status", "--porcelain"])
        if st.returncode == 0:
            n = len([ln for ln in st.stdout.splitlines() if ln.strip()])
            if n:
                parts += f"  {DIRTY} {n}"
        ab = run(["rev-list", "--left-right", "--count", "@{u}...HEAD"])
        if ab.returncode == 0 and ab.stdout.strip():
            try:
                behind, ahead = ab.stdout.split()
                if int(ahead):  parts += f"  {AHEAD}{ahead}"
                if int(behind): parts += f"  {BEHIND}{behind}"
            except ValueError:
                pass
        return parts + " "
    except Exception:
        return None


def short_path(cwd):
    home = os.path.expanduser("~")
    if cwd == home:
        return f"{HOME} ~"
    p = cwd
    if cwd.startswith(home + os.sep):
        p = "~" + cwd[len(home):]
    comps = [c for c in p.split(os.sep) if c]
    tilde = p.startswith("~")
    if tilde:
        comps = comps[1:]
    shown = ("…/" + "/".join(comps[-3:])) if len(comps) > 3 else "/".join(comps)
    if tilde:
        return f"{FOLDER} ~/{shown}" if shown else f"{HOME} ~"
    return f"{FOLDER} /{shown}" if shown else f"{FOLDER} /"


def last_prompt_text(tp):
    try:
        if not tp or not os.path.exists(tp):
            return ""
        with open(tp) as f:
            for ln in reversed(f.readlines()):
                ln = ln.strip()
                if not ln:
                    continue
                o = json.loads(ln)
                if o.get("type") == "user" and not o.get("isMeta") and "message" in o:
                    mc = o["message"].get("content", "")
                    if isinstance(mc, list):
                        txt = " ".join(p.get("text", "") for p in mc
                                       if isinstance(p, dict) and p.get("type") == "text")
                    else:
                        txt = mc if isinstance(mc, str) else ""
                    txt = txt.strip()
                    if txt:
                        return txt[:50] + ("…" if len(txt) > 50 else "")
    except Exception:
        pass
    return ""


# ── Main ──
def main():
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}

    def g(path, default=None):
        cur = data
        for key in path.split("."):
            if isinstance(cur, dict) and key in cur and cur[key] is not None:
                cur = cur[key]
            else:
                return default
        return cur

    cwd     = g("workspace.current_dir") or g("cwd") or os.getcwd()
    model   = g("model.display_name", "Claude")
    sess    = (g("session_id", "") or "")[:8]
    cw      = data.get("context_window") or {}
    limit   = cw.get("context_window_size") or 200000
    used_tk = cw.get("total_input_tokens") or 0
    pct     = cw.get("used_percentage")
    if pct is None:
        pct = (used_tk / limit * 100) if limit else 0
    pct = max(0.0, min(100.0, float(pct)))
    over200 = bool(data.get("exceeds_200k_tokens")) and limit >= 1_000_000
    effort  = g("effort.level")
    cost    = g("cost.total_cost_usd")
    rl5     = g("rate_limits.five_hour.used_percentage")
    rl7     = g("rate_limits.seven_day.used_percentage")
    clock   = datetime.now().strftime("%H:%M")

    cols = term_width()

    # ── Line 1: workspace + all chips (alternating SLATE/DARK so caps stay visible)
    req = [(f" {short_path(cwd)} ", DIRFG, BLUE)]
    gs = git_segment(cwd)
    if gs:
        req.append((gs, BLUE, NAVY))

    chips = []  # (text, fg)
    if rl5 is not None or rl7 is not None:
        def rl(v):
            return (f"{fg(gauge_color(v))}{v:.0f}%{fg(TIMEFG)}" if v is not None else "–")
        chips.append((f" 5h {rl(rl5)}  7d {rl(rl7)} ", TIMEFG))
    if effort:
        chips.append((f" {BOLT} {effort} ", TIMEFG))
    if cost is not None:
        chips.append((f" {DOLLAR} {cost:.2f} ", TIMEFG))
    chips.append((f" {CLOCK} {clock} ", TIMEFG))
    if sess:
        chips.append((f" {FINGER} {sess} ", TIMEFG))

    opt = [(t, f, (SLATE if i % 2 == 0 else DARK)) for i, (t, f) in enumerate(chips)]

    # width-safety: drop trailing chips (then last-prompt) if line 1 overflows
    lp = last_prompt_text(g("transcript_path"))

    def render1(optsegs, prompt):
        line = chain(req + optsegs)
        if prompt:
            line += f"  {fg(DIM)}╶ {prompt}{RESET}"
        return line

    line1 = render1(opt, lp)
    while vlen(line1) > cols and (lp or opt):
        if lp:
            lp = ""
        elif opt:
            opt.pop()
        line1 = render1(opt, lp)

    # ── Line 2: model + FULL-WIDTH context gauge, rounded pill, space-offset
    warn = f" {fg(ORANGE)}{WARN}" if over200 else ""
    prefix = (
        " " + fg(NAVY) + CAPL                                   # leading space + left cap
        + bg(NAVY) + fg(LAV) + f" {ROBOT} {model} "            # model
        + fg(NAVY) + bg(SLATE) + SEP                           # navy -> slate
        + bg(SLATE) + fg(DIRFG) + f" {pct:.0f}% "             # percent
        + fg(TIMEFG) + f"· {dotted(used_tk)} / {humanize(limit)}" + warn
        + bg(SLATE) + "  "                                     # gap before bar
    )
    suffix = bg(SLATE) + " " + RESET + fg(SLATE) + SEP + RESET + " "  # cap + trailing space
    bar_cells = cols - dwidth(prefix) - dwidth(suffix) - 1  # display-width aware, -1 slack
    bar = bg(SLATE) + wide_bar(pct, bar_cells, compaction_frac(limit), bar_color(pct, limit))
    line2 = prefix + bar + suffix

    out = line1 + "\n" + line2
    if os.environ.get("SL_DEBUG"):
        out += (f"\n[debug] width={cols} via={_WIDTH_SRC} | "
                f"L2codepoints={vlen(line2)} L2dwidth={dwidth(line2)} "
                f"bar_cells={bar_cells} robot_dwidth={dwidth(ROBOT)}")
    sys.stdout.write(out)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stdout.write(f"\033[91mstatusline error: {e}\033[0m")
