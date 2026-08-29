"""Tidy up the portfolio: reorder, feature, rename or delete projects."""
from __future__ import annotations

import shutil

from common import (
    C, PROJECTS_DIR, ask, ask_multiline, ask_yes, banner, err, load_data, ok,
    pause, save_data, say, step,
)


def show(projects: list[dict]) -> None:
    step("Your projects")
    if not projects:
        say(f"{C['dim']}none yet - use Add Project.bat{C['r']}")
        return
    for i, p in enumerate(projects, 1):
        star = f"{C['yl']}*{C['r']}" if p.get("featured") else " "
        print(f"   {star} {C['b']}{i:>2}{C['r']}. {p.get('title', '?')}"
              f"   {C['dim']}{p.get('kind', '')} * {p.get('summary', '')[:56]}{C['r']}")
    print(f"\n   {C['dim']}* = featured at the top of the page{C['r']}")


def pick(projects: list[dict], what: str) -> int | None:
    raw = ask(f"Which project to {what}? (number, or Enter to go back)")
    if not raw.isdigit():
        return None
    i = int(raw) - 1
    if 0 <= i < len(projects):
        return i
    err("no project with that number")
    return None


def edit_profile(data: dict) -> None:
    p = data.setdefault("profile", {})
    head = p.setdefault("headline", {})
    step("Edit your details")
    say(f"{C['dim']}Press Enter on any line to keep it as it is.{C['r']}")
    p["name"] = ask("Display name", p.get("name", ""))
    p["monogram"] = ask("Monogram", p.get("monogram", ""))
    p["kicker"] = ask("Your role", p.get("kicker", ""))
    p["status"] = ask("Small line above the headline", p.get("status", ""))
    head["lead"] = ask("Headline, first half", head.get("lead", ""))
    head["accent"] = ask("Headline, gold half", head.get("accent", ""))
    p["intro"] = ask("Paragraph under the headline", p.get("intro", ""))
    p["focus"] = ask("Small line at the foot of the hero", p.get("focus", ""))
    p["location"] = ask("Location", p.get("location", ""))
    p["email"] = ask("Contact email", p.get("email", ""))
    p["github"] = ask("GitHub URL", p.get("github", ""))
    p["linkedin"] = ask("LinkedIn URL (shown in the footer)", p.get("linkedin", ""))
    ok("profile updated")


def edit_toolkit(data: dict) -> None:
    current = data.get("toolkit", [])
    step("The toolkit chips")
    say(f"{C['dim']}{', '.join(current) or 'empty'}{C['r']}")
    raw = ask("Comma separated list", ", ".join(current))
    data["toolkit"] = [t.strip() for t in raw.split(",") if t.strip()]
    ok(f"{len(data['toolkit'])} chips")


def edit_project(pr: dict) -> None:
    step(f"Editing {pr.get('title')}")
    pr["title"] = ask("Name", pr.get("title", ""))
    pr["summary"] = ask("One-line summary", pr.get("summary", ""))
    if ask_yes("Rewrite the long description?", False):
        pr["description"] = ask_multiline("Description")
    tags = ask("Tags (comma separated)", ", ".join(pr.get("tags", [])))
    pr["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    pr["date"] = ask("Date shown", pr.get("date", ""))
    ok("updated")


def main() -> None:
    banner("Manage your portfolio")
    data = load_data()
    projects = data["projects"]

    while True:
        show(projects)
        print()
        print(f"      {C['b']}1{C['r']}. Feature / unfeature a project")
        print(f"      {C['b']}2{C['r']}. Move a project to the top")
        print(f"      {C['b']}3{C['r']}. Edit a project's text")
        print(f"      {C['b']}4{C['r']}. Delete a project")
        print(f"      {C['b']}5{C['r']}. Edit your name, headline and links")
        print(f"      {C['b']}6{C['r']}. Edit the toolkit chips")
        print(f"      {C['b']}7{C['r']}. Save and close")
        choice = ask("choose 1-7", "7")

        if choice == "1":
            i = pick(projects, "feature")
            if i is not None:
                projects[i]["featured"] = not projects[i].get("featured")
                ok(("featured " if projects[i]["featured"] else "unfeatured ")
                   + projects[i]["title"])
        elif choice == "2":
            i = pick(projects, "move to the top")
            if i is not None:
                projects.insert(0, projects.pop(i))
                ok("moved")
        elif choice == "3":
            i = pick(projects, "edit")
            if i is not None:
                edit_project(projects[i])
        elif choice == "4":
            i = pick(projects, "delete")
            if i is not None:
                pr = projects[i]
                if ask_yes(f"Delete '{pr['title']}' and its files?", False):
                    shutil.rmtree(PROJECTS_DIR / pr.get("id", ""), ignore_errors=True)
                    projects.pop(i)
                    ok("deleted")
        elif choice == "5":
            edit_profile(data)
        elif choice == "6":
            edit_toolkit(data)
        else:
            break

        save_data(data)

    save_data(data)
    print()
    ok("saved")
    say(f"Run {C['cy']}Publish.bat{C['r']} to push the changes to your live site.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  cancelled")
    except Exception as e:
        err(f"{type(e).__name__}: {e}")
    pause()
