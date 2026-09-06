"""Gate the source code shown on the site.

Runs over every file listed in data/portfolio.js and writes data/previews.js,
which holds a short readable excerpt of each file plus a decorative filler
block for the locked region. The site renders only what lands in that file,
so nothing else ever reaches a visitor.

Full source for a gated project is moved into _private/ (git-ignored), which
keeps your working copy intact while taking the file off the live site. The
five website projects are the exception: their files stay where they are
because the live demos need them, so those are gated in the listing only.

    python tools/protect.py            gate everything and rewrite previews.js
    python tools/protect.py --check    report what would happen, change nothing
    python tools/protect.py --restore  pull _private/ back into place
"""
from __future__ import annotations

import json
import random
import shutil
import sys
from pathlib import Path

from common import C, ROOT, banner, load_data, ok, say, step, warn

PRIVATE = ROOT / "_private"
OUT = ROOT / "data" / "previews.js"

# How many lines stay readable above the lock.
PREVIEW_LINES = 35

# Files below this are shown whole: there is nothing to protect in a stub.
SHORT_FILE = 20

# Documentation is the selling point, so it is never gated.
OPEN_SUFFIXES = {".md", ".txt", ".rst"}
OPEN_NAMES = {"license", "licence", ".gitignore", "requirements.txt"}

# Where each preview starts, 1-indexed. Anything not listed starts at line 1.
# These windows were picked by hand so the visible code is real work rather
# than a banner comment or an import block.
START_AT = {
    "projects/quantdesk-terminal/quantdesk_terminal.py": 60,
    "projects/terminal-v3/TerminalV3.py": 60,
    "projects/options-calculator/optionCalc.py": 59,
    "projects/capital-decision-dashboard/capitalDash.py": 65,
    "projects/quantdesk-terminal/predict1.py": 479,
    "projects/investpro-elite/main.js": 72,
    "projects/investpro-elite/stock-picks.js": 186,
    "projects/verdant-apex-capital/script.js": 711,
}

# Listed in the file manifest, never previewed.
NO_PREVIEW: set[str] = {
    "projects/quantdesk-terminal/stock2.py",
}

LANG = {
    ".py": "python", ".pyw": "python", ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".html": "html", ".css": "css", ".json": "json",
    ".md": "markdown", ".txt": "text", ".bat": "batch", ".sh": "shell",
}

# Vocabulary for the filler block. None of it comes from your files.
FILL_WORDS = (
    "value result window frame series matrix sample buffer handle vector index "
    "config record cursor factor weight signal bucket target source output "
    "compute resolve render update format collect measure adjust extend"
).split()
FILL_KW = ("if", "for", "return", "def", "self", "while", "with", "in", "not", "and")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_open(path: Path) -> bool:
    return path.suffix.lower() in OPEN_SUFFIXES or path.name.lower() in OPEN_NAMES


def demo_projects(data: dict) -> set[str]:
    """Project ids whose files must stay on disk because a demo serves them."""
    live = set()
    for p in data.get("projects", []):
        demo = (p.get("demo") or "").strip()
        if demo.startswith(f"projects/{p.get('id')}/"):
            live.add(p["id"])
    return live


def locate(rel_path: str) -> Path | None:
    """A gated file lives either in place or, once gated, under _private/."""
    for base in (ROOT, PRIVATE):
        candidate = base / rel_path
        if candidate.is_file():
            return candidate
    return None


def read_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def filler(seed_text: str, lines: int, width: int) -> str:
    """Plausible-looking code shaped text with no relation to any real file."""
    rng = random.Random(seed_text)
    out: list[str] = []
    depth = 1
    for _ in range(lines):
        if rng.random() < 0.10:
            out.append("")
            continue
        depth = max(1, min(4, depth + rng.choice([-1, 0, 0, 0, 1])))
        room = max(12, width - depth * 4)
        parts: list[str] = []
        if rng.random() < 0.22:
            parts.append(rng.choice(FILL_KW))
        while len(" ".join(parts)) < room * rng.uniform(0.45, 0.95):
            word = rng.choice(FILL_WORDS)
            roll = rng.random()
            if roll < 0.18:
                parts.append(f"{word}({rng.choice(FILL_WORDS)})")
            elif roll < 0.32:
                parts.append(f"{word}[{rng.randint(0, 96)}]")
            elif roll < 0.44:
                parts.append(f"{word} = {rng.choice(FILL_WORDS)}")
            elif roll < 0.52:
                parts.append(f'"{word}"')
            else:
                parts.append(word)
        out.append(" " * (depth * 4) + " ".join(parts)[:room])
    return "\n".join(out)


def entry_for(rel_path: str, name: str, live: bool) -> dict | None:
    src = locate(rel_path)
    if src is None:
        warn(f"missing, skipped: {rel_path}")
        return None

    lines = read_lines(src)
    while lines and not lines[-1].strip():
        lines.pop()
    total = len(lines)
    suffix = src.suffix.lower()
    rec = {
        "name": name or src.name,
        "lang": LANG.get(suffix, "text"),
        "totalLines": total,
        "locked": False,
        "shownFrom": 1,
        "shownTo": total,
        "hiddenLines": 0,
        "onDisk": live or is_open(src),
        "preview": "",
        "filler": "",
    }

    if rel_path in NO_PREVIEW:
        rec.update(locked=True, preview="", filler=filler(rel_path, 26, 74),
                   shownFrom=0, shownTo=0, hiddenLines=total, manifestOnly=True)
        return rec

    if is_open(src) or total <= SHORT_FILE:
        rec["preview"] = "\n".join(lines)
        return rec

    start = max(1, min(START_AT.get(rel_path, 1), max(1, total - PREVIEW_LINES)))
    end = min(total, start + PREVIEW_LINES - 1)
    rec.update(
        locked=True,
        preview="\n".join(lines[start - 1:end]),
        shownFrom=start,
        shownTo=end,
        hiddenLines=total - (end - start + 1),
        filler=filler(rel_path, 26, 78),
    )
    return rec


def gate(data: dict, apply: bool) -> tuple[dict, dict, list[Path]]:
    live = demo_projects(data)
    previews: dict[str, dict] = {}
    manifests: dict[str, dict] = {}
    to_move: list[Path] = []

    for proj in data.get("projects", []):
        pid = proj.get("id", "")
        is_live = pid in live

        for item in proj.get("code", []):
            path = item["path"] if isinstance(item, dict) else item
            name = item.get("name", "") if isinstance(item, dict) else ""
            rec = entry_for(path, name, is_live)
            if rec:
                previews[path] = rec

        # The manifest replaces the old download list: names and sizes only.
        rows: list[dict] = []
        seen: set[str] = set()
        listed = [i["path"] if isinstance(i, dict) else i for i in proj.get("downloads", [])]
        listed += [p for p in NO_PREVIEW if p.startswith(f"projects/{pid}/")]
        for path in listed:
            src = locate(path)
            if src is None or path in seen or is_open(src):
                continue
            seen.add(path)
            rows.append({
                "name": path.split(f"projects/{pid}/", 1)[-1],
                "lines": len(read_lines(src)),
                "locked": not is_live,
            })
        if rows:
            manifests[pid] = {
                "files": sorted(rows, key=lambda r: r["name"]),
                "totalFiles": len(rows),
                "totalLines": sum(r["lines"] for r in rows),
                "lockedFiles": sum(1 for r in rows if r["locked"]),
            }

        if is_live:
            continue
        for item in list(proj.get("code", [])) + list(proj.get("downloads", [])):
            path = item["path"] if isinstance(item, dict) else item
            src = ROOT / path
            if src.is_file() and not is_open(src) and src not in to_move:
                to_move.append(src)

    if apply:
        for src in to_move:
            dest = PRIVATE / src.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        for stale in sorted(ROOT.joinpath("projects").rglob("*"), reverse=True):
            if stale.is_dir() and not any(stale.iterdir()):
                try:
                    stale.rmdir()
                except OSError:      # read-only or sandboxed filesystem
                    pass

    return previews, manifests, to_move


def write_previews(previews: dict, manifests: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "/* Generated by tools/protect.py - do not hand-edit.\n"
        "   Holds the readable excerpt of each source file plus a decorative\n"
        "   filler block for the locked region. Full source is not here. */\n"
        "window.PORTFOLIO_PREVIEWS = "
        + json.dumps(previews, indent=1, ensure_ascii=False) + ";\n"
        "window.PORTFOLIO_MANIFESTS = "
        + json.dumps(manifests, indent=1, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )


def restore() -> None:
    banner("Restore full source")
    if not PRIVATE.exists():
        warn("nothing in _private/ to restore")
        return
    moved = 0
    for src in PRIVATE.rglob("*"):
        if not src.is_file():
            continue
        dest = ROOT / src.relative_to(PRIVATE)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved += 1
    ok(f"restored {moved} file(s) into the project tree")
    warn("these are publishable again - run protect.py before you publish")


def main() -> None:
    args = set(sys.argv[1:])
    if "--restore" in args:
        restore()
        return

    check = "--check" in args
    banner("Lock down the source on your site" + (" (dry run)" if check else ""))

    data = load_data()
    previews, manifests, to_move = gate(data, apply=not check)

    step("Previews")
    locked = sum(1 for r in previews.values() if r["locked"])
    shown = sum(1 for r in previews.values() if not r["locked"])
    for path, rec in previews.items():
        if rec.get("manifestOnly"):
            tag = f"{C['yl']}manifest only{C['r']}"
        elif rec["locked"]:
            tag = (f"{C['gr']}lines {rec['shownFrom']}-{rec['shownTo']} of "
                   f"{rec['totalLines']}{C['r']}")
        else:
            tag = f"{C['dim']}full ({rec['totalLines']} lines){C['r']}"
        print(f"    {path:<62} {tag}")
    print()
    say(f"{locked} file(s) gated, {shown} shown in full")

    if to_move:
        step("Full source taken off the site" if not check else "Would be taken off the site")
        for src in to_move:
            print(f"    {rel(src)}  ->  _private/{rel(src)}")
        print()
        say(f"{len(to_move)} file(s) - your copies stay in _private/, which git ignores")

    if check:
        print()
        warn("dry run: nothing was written or moved")
        return

    write_previews(previews, manifests)
    ok(f"wrote {rel(OUT)}")
    print()
    say("Run Preview Site.bat to look at it, then Publish.bat when it looks right.")


if __name__ == "__main__":
    main()
