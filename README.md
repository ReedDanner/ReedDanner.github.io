# Portfolio

A self-hosted portfolio site. Every project — code, screenshots, live web pages,
PDFs, algorithms, whole applications — lives in this repository and is published
automatically to GitHub Pages.

**Live site:** the link is at the top right of this repository, and in `.portfolio.json`.

---

## Three buttons

| Double-click | What it does |
| --- | --- |
| **Setup GitHub.bat** | Run once. Installs the GitHub CLI, signs you in, creates the repository, switches on GitHub Pages, and hands you the public URL. |
| **Add Project.bat** | Drag a file or a whole project folder onto it. It asks a few questions, copies the files in, and writes the entry. |
| **Publish.bat** | Pushes everything new. The live site updates in about a minute. |

Three extras:

- **Preview Site.bat** — opens the site locally, exactly as visitors will see it, before publishing.
- **Manage Projects.bat** — reorder, feature, rename, or delete projects; edit your headline, links and toolkit.
- **Lock Source.bat** — run this after adding a project. It decides what the site is allowed to show.

## Adding a project

Drag one or many things onto `Add Project.bat`:

- a **folder** — the whole tree is copied, minus `__pycache__`, `node_modules`,
  `.venv`, build output and anything that looks like a credentials file
- a **single script** — shown with syntax highlighting on the project page
- **screenshots** — become the gallery, and the first one becomes the card image
- a **PDF** — embedded in the page, readable without downloading
- a **web project with `index.html`** — gets a live link that really runs

## Source that is public to read, private to use

`Lock Source.bat` (`tools/protect.py`) is what stands between a visitor and a
working copy of a project. It writes `data/previews.js`, which holds a short
readable excerpt of each file plus a filler block that is generated noise, and
it moves the full source into `_private/`. That folder is git-ignored, so your
working copy keeps everything and the live site never receives it.

The site renders only what is in `previews.js`. There is nothing to unblur in
the browser, no download button anywhere, and a request for a locked file's URL
returns 404 because the file is not deployed.

    PREVIEW_LINES   how many lines stay readable, currently 35
    START_AT        where a file's excerpt begins, chosen per file
    NO_PREVIEW      listed in the manifest, never shown
    OPEN_SUFFIXES   .md and .txt, always shown in full

Two things stay public on purpose. Documentation is the selling point, so
READMEs and requirements files are shown whole. The five website projects have
live demos served out of their own folders, so their files must stay deployed;
they are gated in the listing, but anything running in a browser can be read
with view-source, and that is a property of the web rather than of this tool.

    python tools/protect.py --check     see what would change
    python tools/protect.py --restore   pull _private/ back into place

`Publish.bat` refuses to push a project whose source has not been through this
step, unless you tell it to.

## Safety net

Before anything is copied in, and again before every publish, the tools scan for
API keys, tokens and hard-coded passwords. Anything suspicious is shown with the
file and line number, and excluded by default. Public repositories are permanent —
this is the guard rail that matters most.

Files above 45 MB are refused (GitHub warns at 50 MB and rejects 100 MB).

## The page

One page, four numbered sections: the work, how I work, the toolkit, and contact.
LinkedIn sits in the footer, so the site points at the profile rather than the
other way round.

All the wording lives in `data/portfolio.js` and can be changed with
`Manage Projects.bat`, or by editing that file directly — it is plain JSON:

```
profile.headline   the big two-line headline (the second half is gold)
profile.status     the small line above it
approach.points    the three numbered principles
toolkit            the chips in section 03
projects           everything Add Project.bat writes
```

## Layout

```
index.html            the page
assets/style.css      styling
assets/app.js         rendering, search, filters, code viewer
data/portfolio.js     your details and every project entry
projects/<slug>/      the actual files for each project
tools/                the Python behind the .bat buttons
```

## Requirements

Python 3 and Git on Windows. The GitHub CLI is installed for you on first setup.
