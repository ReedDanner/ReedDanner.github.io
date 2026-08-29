"""Add a project to the portfolio.

Usage:
    python tools/add_project.py [file_or_folder ...]

Or just drag files/folders onto "Add Project.bat".
"""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

from common import (
    C, CODE_EXT, DOC_EXT, IMAGE_EXT, MAX_FILE_BYTES, PROJECTS_DIR, ROOT,
    ask, ask_multiline, ask_yes, banner, choose, err, human_size, load_data, ok,
    pause, prettify, save_data, say, scan_secrets, should_skip, slugify, step,
    walk_files, warn,
)

KINDS = [
    ("app", "Application / tool  (a program someone runs)"),
    ("code", "Code / library      (scripts, modules, notebooks)"),
    ("website", "Website / web app   (has an index.html to open live)"),
    ("algorithm", "Algorithm / model   (a technique, a strategy, a solver)"),
    ("research", "Research / analysis (write-ups, backtests, findings)"),
    ("document", "Document / PDF      (reports, decks, papers)"),
    ("design", "Design / visual     (screenshots, mockups, diagrams)"),
    ("other", "Something else"),
]

ENTRY_NAMES = (
    "main.py", "app.py", "__main__.py", "run.py", "index.js", "main.js", "app.js",
    "index.html", "main.cpp", "main.java", "main.go", "main.rs", "readme.md",
)

LANG_TAGS = {
    ".py": "Python", ".pyw": "Python", ".ipynb": "Jupyter", ".js": "JavaScript",
    ".jsx": "React", ".tsx": "React", ".ts": "TypeScript", ".java": "Java",
    ".c": "C", ".cpp": "C++", ".cs": "C#", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".php": "PHP", ".swift": "Swift", ".kt": "Kotlin", ".r": "R", ".sql": "SQL",
    ".sh": "Shell", ".ps1": "PowerShell", ".html": "HTML", ".css": "CSS",
    ".vue": "Vue", ".svelte": "Svelte", ".m": "MATLAB", ".jl": "Julia",
}


def clean_path_arg(raw: str) -> str:
    return raw.strip().strip('"').strip("'").rstrip("\\/")


def gather_sources(argv: list[str]) -> list[Path]:
    sources: list[Path] = []
    for a in argv:
        p = Path(clean_path_arg(a))
        if p.exists():
            sources.append(p)
        else:
            warn(f"skipping (not found): {a}")

    if sources:
        return sources

    step("Which files or folders belong to this project?")
    say(f"{C['dim']}Drag a file or folder into this window and press Enter.")
    say(f"Add as many as you like. Press Enter on an empty line when done.{C['r']}")
    say(f"{C['dim']}(No files? Just press Enter - you can make a link-only entry.){C['r']}")
    while True:
        raw = input(f"  {C['cy']}+{C['r']} path: ").strip()
        if not raw:
            break
        p = Path(clean_path_arg(raw))
        if not p.exists():
            err(f"not found: {p}")
            continue
        sources.append(p)
        ok(f"added {p.name}")
    return sources


def collect(sources: list[Path]) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Return [(src_file, relative_dest)] plus a list of notes about skips."""
    plan: list[tuple[Path, Path]] = []
    notes: list[str] = []
    single_dir = len(sources) == 1 and sources[0].is_dir()

    for src in sources:
        if src.is_file():
            reason = should_skip(src)
            if reason:
                notes.append(f"{src.name} - {reason}")
                continue
            plan.append((src, Path(src.name)))
            continue

        base = src
        for f in walk_files(src):
            reason = should_skip(f)
            if reason:
                notes.append(f"{f.name} - {reason}")
                continue
            try:
                rel = f.relative_to(base)
            except ValueError:
                rel = Path(f.name)
            dest_rel = rel if single_dir else Path(src.name) / rel
            plan.append((f, dest_rel))

    kept: list[tuple[Path, Path]] = []
    for f, rel in plan:
        try:
            size = f.stat().st_size
        except OSError:
            notes.append(f"{f.name} - unreadable")
            continue
        if size > MAX_FILE_BYTES:
            notes.append(f"{rel.as_posix()} - {human_size(size)}, too big for GitHub")
            continue
        kept.append((f, rel))
    return kept, notes


def secret_gate(plan: list[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    flagged: dict[Path, list] = {}
    for f, rel in plan:
        hits = scan_secrets(f)
        if hits:
            flagged[f] = hits

    if not flagged:
        return plan

    print()
    warn(f"{C['b']}Possible API keys or passwords found in {len(flagged)} file(s).{C['r']}")
    say(f"{C['dim']}This portfolio becomes a PUBLIC GitHub repo, so anything published "
        f"here is visible to everyone.{C['r']}")
    print()
    for f, hits in list(flagged.items())[:12]:
        print(f"    {C['yl']}{f.name}{C['r']}")
        for lineno, kind, excerpt in hits[:3]:
            print(f"      line {lineno}  {C['dim']}{kind}:{C['r']}  {excerpt}")
    if len(flagged) > 12:
        say(f"{C['dim']}...and {len(flagged) - 12} more{C['r']}")
    print()

    if ask_yes("Leave these files OUT of the portfolio? (strongly recommended)", True):
        keep = [(f, rel) for f, rel in plan if f not in flagged]
        ok(f"excluded {len(flagged)} file(s)")
        return keep

    warn("including them - remove the keys from those files before you publish")
    return plan


def copy_files(plan: list[tuple[Path, Path]], dest: Path) -> list[Path]:
    written: list[Path] = []
    for src, rel in plan:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, target)
            written.append(target)
        except OSError as e:
            err(f"could not copy {rel.as_posix()}: {e}")
    return written


def rel_web(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def pick_cover(images: list[Path]) -> Path | None:
    if not images:
        return None
    if len(images) == 1:
        return images[0]
    step("Which image should be the cover on the project card?")
    for i, p in enumerate(images[:12], 1):
        print(f"      {C['b']}{i}{C['r']}. {p.name}")
    raw = ask(f"choose 1-{min(len(images), 12)}", "1")
    if raw.isdigit() and 1 <= int(raw) <= min(len(images), 12):
        return images[int(raw) - 1]
    return images[0]


def rank_code(files: list[Path]) -> list[Path]:
    def score(p: Path) -> tuple:
        name = p.name.lower()
        entry = ENTRY_NAMES.index(name) if name in ENTRY_NAMES else 99
        depth = len(p.parts)
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        return (entry, depth, -size)
    return sorted(files, key=score)


def main() -> None:
    banner("Add a project to your portfolio")

    sources = gather_sources(sys.argv[1:])
    plan, notes = collect(sources)

    if notes:
        print()
        say(f"{C['dim']}Left out automatically:{C['r']}")
        for n in notes[:10]:
            say(f"{C['dim']}  * {n}{C['r']}")
        if len(notes) > 10:
            say(f"{C['dim']}  * ...and {len(notes) - 10} more{C['r']}")

    if plan:
        plan = secret_gate(plan)
        total = sum(f.stat().st_size for f, _ in plan)
        print()
        ok(f"{len(plan)} file(s) ready, {human_size(total)}")

    # ------------------------------------------------------------ details
    default_title = prettify(sources[0].name) if sources else ""
    step("Tell people what this is")
    title = ask("Project name", default_title)
    while not title:
        title = ask("Project name (required)")

    summary = ask("One line for the project card (what does it do?)")
    while not summary:
        summary = ask("One line - required, this is what people read first")

    description = ask_multiline(
        "Longer description - the problem, your approach, what is interesting about it")

    kind = choose("What kind of project is it?", KINDS, 0)

    suggested = sorted({
        LANG_TAGS[f.suffix.lower()] for f, _ in plan if f.suffix.lower() in LANG_TAGS
    })
    if suggested:
        say(f"{C['dim']}detected: {', '.join(suggested)}{C['r']}")
    tags_raw = ask("Tags, comma separated (languages, libraries, topics)",
                   ", ".join(suggested[:6]))
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    links = []
    step("Any links? (a GitHub repo, a live site, a write-up)")
    say(f"{C['dim']}Press Enter on an empty label when you are done.{C['r']}")
    while True:
        label = ask("Link label (e.g. 'Source on GitHub')")
        if not label:
            break
        url = ask("URL")
        if url:
            links.append({"label": label, "url": url})
            ok(f"{label} -> {url}")

    featured = ask_yes("Feature this one at the top of the page?", False)

    # ------------------------------------------------------------ write
    data = load_data()
    slug = slugify(title)
    existing = {p.get("id") for p in data["projects"]}
    if slug in existing:
        if ask_yes(f"'{slug}' already exists. Replace it?", True):
            data["projects"] = [p for p in data["projects"] if p.get("id") != slug]
            shutil.rmtree(PROJECTS_DIR / slug, ignore_errors=True)
        else:
            n = 2
            while f"{slug}-{n}" in existing:
                n += 1
            slug = f"{slug}-{n}"

    dest = PROJECTS_DIR / slug
    written: list[Path] = []
    if plan:
        dest.mkdir(parents=True, exist_ok=True)
        written = copy_files(plan, dest)

    images = [p for p in written if p.suffix.lower() in IMAGE_EXT]
    docs = [p for p in written if p.suffix.lower() in DOC_EXT]
    code_all = [p for p in written
                if p.suffix.lower() in CODE_EXT and p.suffix.lower() not in IMAGE_EXT]
    code = rank_code(code_all)[:6]
    other = [p for p in written if p not in images and p not in docs and p not in code_all]

    demo = ""
    html_roots = [p for p in written if p.name.lower() == "index.html"]
    if not html_roots:
        html_roots = [p for p in written if p.suffix.lower() in (".html", ".htm")]
    if html_roots:
        candidate = min(html_roots, key=lambda p: len(p.parts))
        if kind == "website" or ask_yes(
                f"Open {candidate.name} as a live demo on the site?", kind == "website"):
            demo = rel_web(candidate)

    cover = pick_cover(images)

    project = {
        "id": slug,
        "title": title,
        "summary": summary,
        "description": description,
        "kind": kind,
        "tags": tags,
        "date": date.today().strftime("%b %Y"),
        "featured": featured,
        "links": links,
        "cover": rel_web(cover) if cover else "",
        "images": [rel_web(p) for p in images[:16]],
        "docs": [rel_web(p) for p in docs[:4]],
        "code": [{"path": rel_web(p), "name": p.name} for p in code],
        "downloads": [
            {"path": rel_web(p), "name": p.name, "size": human_size(p.stat().st_size)}
            for p in (other + [c for c in code_all if c not in code])[:20]
        ],
        "demo": demo,
    }

    data["projects"].insert(0, project)
    save_data(data)

    print()
    ok(f"{C['b']}{title}{C['r']} added to your portfolio")
    if written:
        say(f"files live in  projects/{slug}/")
    say(f"{len(images)} image(s) * {len(docs)} PDF(s) * {len(code)} code file(s) shown")
    print()
    say(f"{C['b']}Next:{C['r']} double-click {C['cy']}Preview Site.bat{C['r']} to look at it,")
    say(f"      then {C['cy']}Publish.bat{C['r']} to put it online.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  cancelled - nothing was changed")
    except Exception as e:  # keep the window open so the message is readable
        err(f"{type(e).__name__}: {e}")
    pause()
