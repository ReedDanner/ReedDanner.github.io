"""One-time setup: connect this folder to GitHub and turn on GitHub Pages.

Run it once. After that you only ever need Publish.bat.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from common import (
    C, ROOT, ask, ask_yes, banner, err, gh_path, git, git_ok, have, load_data,
    ok, open_url, pause, save_data, say, step, warn,
)

WINGET_ID = "GitHub.cli"


def run(cmd: list[str], capture: bool = True, check: bool = False):
    return subprocess.run(cmd, cwd=ROOT, text=True, check=check,
                          capture_output=capture, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- git identity

def ensure_git() -> None:
    step("Checking git")
    if not have("git"):
        err("git is not installed.")
        say("Install it from https://git-scm.com/download/win, then run this again.")
        open_url("https://git-scm.com/download/win")
        raise SystemExit(1)
    ok(f"git found - {run(['git', '--version']).stdout.strip()}")

    name = run(["git", "config", "--global", "user.name"]).stdout.strip()
    email = run(["git", "config", "--global", "user.email"]).stdout.strip()
    if not name or not email:
        say("Git needs a name and email to stamp on your commits (this is public).")
        profile = load_data().get("profile", {})
        name = name or ask("Your name", profile.get("name", ""))
        email = email or ask("Your email", "")
        if name:
            run(["git", "config", "--global", "user.name", name])
        if email:
            run(["git", "config", "--global", "user.email", email])
    ok(f"committing as {name} <{email}>")


# ---------------------------------------------------------------- gh cli

def ensure_gh() -> str:
    step("Checking the GitHub command line tool")
    gh = gh_path()
    if gh:
        ok("GitHub CLI found")
        return gh

    say("Not installed yet. It is the piece that creates the repo for you.")
    if not have("winget"):
        err("winget is unavailable, so I cannot install it automatically.")
        say("Install GitHub CLI from https://cli.github.com/ and run this again.")
        open_url("https://cli.github.com/")
        raise SystemExit(1)

    if not ask_yes("Install GitHub CLI now? (about 15 seconds)", True):
        raise SystemExit(0)

    say(f"{C['dim']}installing...{C['r']}")
    run(["winget", "install", "--id", WINGET_ID, "-e", "--source", "winget",
         "--accept-package-agreements", "--accept-source-agreements"], capture=False)

    gh = gh_path()
    if not gh:
        err("Installed, but I still cannot find gh.exe.")
        say("Close this window, open a new one, and run Setup GitHub.bat again.")
        raise SystemExit(1)
    ok("GitHub CLI installed")
    return gh


def ensure_auth(gh: str) -> str:
    step("Signing you in to GitHub")
    if run([gh, "auth", "status"]).returncode != 0:
        say("A browser window will open. Sign in, paste the code shown here, and approve.")
        say(f"{C['dim']}If you do not have a GitHub account yet, create one on that page "
            f"first - it is free.{C['r']}")
        print()
        subprocess.run([gh, "auth", "login", "--hostname", "github.com",
                        "--git-protocol", "https", "--web"], cwd=ROOT, check=False)
        if run([gh, "auth", "status"]).returncode != 0:
            err("Sign-in did not complete. Run Setup GitHub.bat again when you are ready.")
            raise SystemExit(1)

    user = run([gh, "api", "user", "--jq", ".login"]).stdout.strip()
    if not user:
        err("Signed in, but GitHub did not return a username.")
        raise SystemExit(1)
    ok(f"signed in as {C['b']}{user}{C['r']}")
    run([gh, "auth", "setup-git"])
    return user


# ---------------------------------------------------------------- profile

def tidy_url(url: str) -> str:
    url = url.strip()
    if url and not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    return url


def fill_profile(user: str) -> None:
    step("Your details")
    say(f"{C['dim']}Press Enter on any line to keep what is already there.{C['r']}")
    data = load_data()
    p = data.setdefault("profile", {})
    head = p.setdefault("headline", {})

    p["name"] = ask("Display name", p.get("name") or user)
    p["monogram"] = ask(
        "Monogram for the corner",
        p.get("monogram") or "".join(w[0] for w in p["name"].split()[:2]).upper())
    p["kicker"] = ask("Your field, in a few words (shown above the headline)", p.get("kicker") or "")
    p["status"] = ask("Status line under the buttons, e.g. roles you want (blank to hide it)",
                      p.get("status") or "")

    say(f"{C['dim']}The big headline runs over two lines, one short sentence each.{C['r']}")
    head["lead"] = ask("Headline, first line", head.get("lead") or "")
    head["accent"] = ask("Headline, second line", head.get("accent") or "")

    p["intro"] = ask("Short paragraph under the headline", p.get("intro") or "")
    p["focus"] = ask("Current focus (shown in the approach section)", p.get("focus") or "")
    p["location"] = ask("Location (blank to hide it)", p.get("location") or "")

    p["github"] = f"https://github.com/{user}"
    say(f"{C['dim']}LinkedIn sits in the footer, so people who find the site can find you.{C['r']}")
    p["linkedin"] = tidy_url(ask("Your LinkedIn URL", p.get("linkedin") or ""))
    p["email"] = ask("Contact email", p.get("email") or "").replace("mailto:", "")

    save_data(data)
    ok("saved to data/portfolio.js")


# ---------------------------------------------------------------- repo

def choose_repo(user: str) -> tuple[str, str]:
    step("Where should it live?")
    print(f"      {C['b']}1{C['r']}. {user}.github.io      "
          f"{C['dim']}-> https://{user}.github.io  (shortest, best for LinkedIn){C['r']}")
    print(f"      {C['b']}2{C['r']}. portfolio             "
          f"{C['dim']}-> https://{user}.github.io/portfolio{C['r']}")
    print(f"      {C['b']}3{C['r']}. pick my own name")
    raw = ask("choose 1-3", "1")
    if raw == "2":
        return "portfolio", f"https://{user}.github.io/portfolio/"
    if raw == "3":
        name = ask("Repository name") or "portfolio"
        if name == f"{user}.github.io":
            return name, f"https://{user}.github.io/"
        return name, f"https://{user}.github.io/{name}/"
    return f"{user}.github.io", f"https://{user}.github.io/"


def init_repo() -> None:
    if not (ROOT / ".git").exists():
        git("init")
        git("branch", "-M", "main", check=False)
        ok("git repository created in this folder")
    else:
        git("branch", "-M", "main", check=False)


def commit_all(message: str) -> bool:
    git("add", "-A")
    if not git("diff", "--cached", "--quiet", check=False).returncode:
        return False
    git("commit", "-m", message)
    return True


def create_remote(gh: str, user: str, repo: str) -> None:
    step("Creating the repository on GitHub")
    existing = run([gh, "repo", "view", f"{user}/{repo}", "--json", "name"])
    has_origin = git_ok("remote", "get-url", "origin")

    if existing.returncode == 0:
        ok(f"{user}/{repo} already exists on GitHub")
        if not has_origin:
            git("remote", "add", "origin", f"https://github.com/{user}/{repo}.git")
        git("push", "-u", "origin", "main", check=False, capture=False)
        return

    say("It will be PUBLIC - that is what makes the link shareable and Pages free.")
    r = run([gh, "repo", "create", repo, "--public", "--source", ".",
             "--remote", "origin", "--push",
             "--description", "My portfolio of projects, tools and research."],
            capture=True)
    if r.returncode != 0:
        err("Could not create the repository.")
        say(r.stderr.strip() or r.stdout.strip())
        raise SystemExit(1)
    ok(f"pushed to https://github.com/{user}/{repo}")


def enable_pages(gh: str, user: str, repo: str) -> None:
    step("Turning on GitHub Pages")
    check = run([gh, "api", f"repos/{user}/{repo}/pages"])
    if check.returncode == 0:
        ok("Pages is already on")
        return
    r = run([gh, "api", "--method", "POST", f"repos/{user}/{repo}/pages",
             "-f", "source[branch]=main", "-f", "source[path]=/"])
    if r.returncode == 0:
        ok("Pages enabled - the first build takes a minute or two")
        return
    if "409" in (r.stderr or "") or "already" in (r.stderr or "").lower():
        ok("Pages was already on")
        return
    warn("Could not switch Pages on automatically.")
    say(f"Do it by hand here (Source: 'Deploy from a branch' -> main -> / root):")
    say(f"  https://github.com/{user}/{repo}/settings/pages")
    open_url(f"https://github.com/{user}/{repo}/settings/pages")


def wait_for_site(url: str) -> None:
    import urllib.error
    import urllib.request
    say(f"{C['dim']}waiting for the first build...{C['r']}")
    for _ in range(20):
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                if resp.status == 200:
                    ok("site is live")
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(9)
    warn("still building - it usually appears within a couple of minutes.")


def save_site_config(user: str, repo: str, url: str) -> None:
    (ROOT / ".portfolio.json").write_text(
        json.dumps({"user": user, "repo": repo, "url": url}, indent=2), encoding="utf-8")


def main() -> None:
    banner("Set up your portfolio on GitHub")
    say("This runs once. It creates the repository, publishes the site,")
    say("and gives you a link you can paste straight into LinkedIn.")

    ensure_git()
    gh = ensure_gh()
    user = ensure_auth(gh)
    fill_profile(user)
    repo, url = choose_repo(user)

    step("Publishing")
    init_repo()
    commit_all("Add portfolio site")
    create_remote(gh, user, repo)
    enable_pages(gh, user, repo)
    save_site_config(user, repo, url)

    print()
    banner("Done")
    say(f"Repository:  {C['cy']}https://github.com/{user}/{repo}{C['r']}")
    say(f"Your site:   {C['b']}{C['cy']}{url}{C['r']}")
    print()
    say("Paste that link into LinkedIn under Contact info -> Website,")
    say("or as a Featured link on your profile.")
    print()
    wait_for_site(url)
    if ask_yes("Open the site now?", True):
        open_url(url)
    print()
    say(f"From now on: add projects with {C['cy']}Add Project.bat{C['r']}, "
        f"then run {C['cy']}Publish.bat{C['r']}.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  cancelled")
    except SystemExit:
        pass
    except Exception as e:
        err(f"{type(e).__name__}: {e}")
    pause()
