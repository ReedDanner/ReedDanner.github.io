"""Publish: push everything new to GitHub so the live site updates."""
from __future__ import annotations

import json
from pathlib import Path

from common import (
    C, MAX_FILE_BYTES, ROOT, ask, ask_yes, banner, err, git, git_ok, human_size,
    load_data, ok, open_url, pause, say, scan_secrets, step, warn,
)
from protect import gate as gate_check

CONFIG = ROOT / ".portfolio.json"


def site_config() -> dict:
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def changed_paths() -> list[tuple[str, Path]]:
    out = git("status", "--porcelain", "-uall").stdout.splitlines()
    items: list[tuple[str, Path]] = []
    for line in out:
        if not line.strip():
            continue
        rest = line[3:].strip().strip('"')
        if " -> " in rest:                       # renames
            rest = rest.split(" -> ", 1)[1]
        items.append((line[:2].strip() or "?", ROOT / rest))
    return items


def preflight(items: list[tuple[str, Path]]) -> bool:
    """Returns False when the user decides not to publish."""
    files = [p for _, p in items if p.is_file()]

    big = [p for p in files if p.stat().st_size > MAX_FILE_BYTES]
    if big:
        warn("These files are too big for GitHub and must be removed first:")
        for p in big:
            say(f"  {p.relative_to(ROOT).as_posix()} - {human_size(p.stat().st_size)}")
        return False

    _, _, ungated = gate_check(load_data(), apply=False)
    if ungated:
        print()
        warn(f"{C['b']}{len(ungated)} source file(s) would go public in full:{C['r']}")
        for p in ungated[:10]:
            say(f"  {p.relative_to(ROOT).as_posix()}")
        if len(ungated) > 10:
            say(f"  {C['dim']}...and {len(ungated) - 10} more{C['r']}")
        print()
        say("Run Lock Source.bat first - it keeps a readable excerpt on the site")
        say("and moves the rest into _private/, which is never pushed.")
        print()
        if not ask_yes("Publish the full source anyway?", False):
            say("Nothing was published.")
            return False

    flagged = []
    for p in files:
        hits = scan_secrets(p)
        if hits:
            flagged.append((p, hits))

    if flagged:
        print()
        warn(f"{C['b']}Possible API keys or passwords in {len(flagged)} file(s) "
             f"about to go public:{C['r']}")
        for p, hits in flagged[:10]:
            print(f"    {C['yl']}{p.relative_to(ROOT).as_posix()}{C['r']}")
            for lineno, kind, excerpt in hits[:2]:
                print(f"      line {lineno}  {C['dim']}{kind}:{C['r']}  {excerpt}")
        print()
        say("Once a key is pushed to a public repo it should be treated as leaked,")
        say("even if you delete it afterwards.")
        print()
        if not ask_yes("Publish anyway?", False):
            say("Nothing was published. Remove the keys, then run this again.")
            return False
    return True


def main() -> None:
    banner("Publish your portfolio")

    if not (ROOT / ".git").exists():
        err("This folder is not connected to GitHub yet.")
        say(f"Run {C['cy']}Setup GitHub.bat{C['r']} first - it only takes a minute.")
        return

    cfg = site_config()
    data = load_data()
    projects = data.get("projects", [])

    items = changed_paths()
    if not items:
        ok("Everything is already published - nothing has changed.")
        if cfg.get("url"):
            say(f"Your site: {C['cy']}{cfg['url']}{C['r']}")
        return

    step("What is about to go online")
    shown = 0
    for code, path in items:
        try:
            rel = path.relative_to(ROOT).as_posix()
        except ValueError:
            rel = str(path)
        label = {"??": "new", "A": "new", "M": "changed", "D": "removed"}.get(code, code)
        print(f"    {C['dim']}{label:>8}{C['r']}  {rel}")
        shown += 1
        if shown >= 25:
            say(f"{C['dim']}...and {len(items) - shown} more{C['r']}")
            break

    print()
    say(f"{len(projects)} project(s) will be on the site.")

    if not preflight(items):
        return

    print()
    if not ask_yes("Publish now?", True):
        say("Cancelled - nothing was pushed.")
        return

    newest = projects[0]["title"] if projects else "portfolio"
    default_msg = f"Add {newest}" if len(items) < 60 else "Update portfolio"
    msg = ask("Commit message", default_msg) or default_msg

    step("Uploading")
    git("add", "-A")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        ok("nothing to commit")
    else:
        git("commit", "-m", msg)
        ok(f'committed "{msg}"')

    if not git_ok("remote", "get-url", "origin"):
        err("No GitHub remote is set. Run Setup GitHub.bat.")
        return

    push = git("push", "origin", "main", check=False)
    if push.returncode != 0:
        stderr = (push.stderr or "") + (push.stdout or "")
        if "rejected" in stderr or "non-fast-forward" in stderr:
            warn("GitHub has changes this computer does not. Pulling them in first...")
            git("pull", "--rebase", "origin", "main", check=False, capture=False)
            push = git("push", "origin", "main", check=False)
        if push.returncode != 0:
            err("Push failed:")
            say((push.stderr or push.stdout or "").strip()[:900])
            return
    ok("pushed to GitHub")

    url = cfg.get("url", "")
    print()
    banner("Published")
    if url:
        say(f"Live site: {C['b']}{C['cy']}{url}{C['r']}")
        say(f"{C['dim']}GitHub takes 30-90 seconds to rebuild. "
            f"Refresh with Ctrl+F5 if it looks stale.{C['r']}")
        print()
        if ask_yes("Open it?", True):
            open_url(url)
    else:
        say("Pushed. Your site URL is on the repository's Settings -> Pages screen.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  cancelled")
    except Exception as e:
        err(f"{type(e).__name__}: {e}")
    pause()
