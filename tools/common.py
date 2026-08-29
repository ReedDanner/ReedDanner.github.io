"""Shared helpers for the portfolio tools."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "portfolio.js"
PROJECTS_DIR = ROOT / "projects"

# ---------------------------------------------------------------- console

if os.name == "nt":
    os.system("")  # turns on ANSI escape handling in the Windows console

for _stream in (sys.stdout, sys.stderr):
    try:  # never let an odd console codepage crash a tool mid-run
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

C = {
    "r": "\033[0m", "b": "\033[1m", "dim": "\033[2m",
    "cy": "\033[96m", "gr": "\033[92m", "yl": "\033[93m",
    "rd": "\033[91m", "bl": "\033[94m",
}


def banner(text: str) -> None:
    line = "=" * max(46, len(text) + 4)
    print(f"\n{C['cy']}{line}\n  {C['b']}{text}{C['r']}{C['cy']}\n{line}{C['r']}\n")


def say(msg: str) -> None:
    print(f"  {msg}")


def ok(msg: str) -> None:
    print(f"  {C['gr']}[ok]{C['r']} {msg}")


def warn(msg: str) -> None:
    print(f"  {C['yl']}[!]{C['r']} {msg}")


def err(msg: str) -> None:
    print(f"  {C['rd']}[x]{C['r']} {msg}")


def step(msg: str) -> None:
    print(f"\n{C['b']}{C['bl']}>{C['r']} {C['b']}{msg}{C['r']}")


def ask(prompt: str, default: str = "") -> str:
    hint = f" {C['dim']}[{default}]{C['r']}" if default else ""
    try:
        val = input(f"  {C['cy']}?{C['r']} {prompt}{hint}: ").strip()
    except EOFError:
        return default
    return val or default


def ask_yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    while True:
        val = input(f"  {C['cy']}?{C['r']} {prompt} {C['dim']}[{d}]{C['r']}: ").strip().lower()
        if not val:
            return default
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False


def ask_multiline(prompt: str) -> str:
    print(f"  {C['cy']}?{C['r']} {prompt}")
    print(f"    {C['dim']}(write as much as you like - press Enter twice when done){C['r']}")
    lines: list[str] = []
    blanks = 0
    while True:
        try:
            line = input("    ")
        except EOFError:
            break
        if not line.strip():
            if not lines:          # nothing typed at all - skip the question
                break
            blanks += 1
            if blanks >= 2:        # a blank line ends a paragraph, two end the answer
                break
            lines.append("")
        else:
            blanks = 0
            lines.append(line.rstrip())
    return "\n".join(lines).strip()


def choose(prompt: str, options: list[tuple[str, str]], default_index: int = 0) -> str:
    print(f"  {C['cy']}?{C['r']} {prompt}")
    for i, (_, label) in enumerate(options, 1):
        print(f"      {C['b']}{i}{C['r']}. {label}")
    while True:
        raw = input(f"  {C['dim']}choose 1-{len(options)} "
                    f"[{default_index + 1}]{C['r']}: ").strip()
        if not raw:
            return options[default_index][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]


def pause() -> None:
    print()
    try:
        input(f"  {C['dim']}Press Enter to close...{C['r']}")
    except EOFError:
        pass


# ---------------------------------------------------------------- data file

DEFAULT_DATA = {
    "profile": {"name": "", "title": "", "bio": "", "avatar": "", "links": []},
    "projects": [],
}


def load_data() -> dict:
    if not DATA_FILE.exists():
        return json.loads(json.dumps(DEFAULT_DATA))
    raw = DATA_FILE.read_text(encoding="utf-8")
    match = re.search(r"window\.PORTFOLIO\s*=\s*(\{.*\})\s*;?\s*$", raw, re.S)
    if not match:
        raise SystemExit("data/portfolio.js is malformed - expected 'window.PORTFOLIO = {...};'")
    data = json.loads(match.group(1))
    data.setdefault("profile", {})
    data.setdefault("projects", [])
    return data


def save_data(data: dict) -> None:
    body = json.dumps(data, indent=2, ensure_ascii=False)
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        "/* Portfolio data. Edited automatically by the tools in /tools.\n"
        "   You can also hand-edit it - it is plain JSON inside window.PORTFOLIO. */\n"
        f"window.PORTFOLIO = {body};\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------- files

def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "project"


def prettify(name: str) -> str:
    s = re.sub(r"[_\-]+", " ", Path(name).stem)
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.title() if s.islower() else s


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


SKIP_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", ".venv", "venv", "env", ".env", "site-packages", ".idea",
    ".ipynb_checkpoints", "dist", "build", ".next", ".cache", ".tox", "bin", "obj",
    "$RECYCLE.BIN", "System Volume Information",
}
SKIP_FILE_EXT = {
    ".pyc", ".pyo", ".pyd", ".class", ".o", ".obj", ".so", ".dll", ".dylib",
    ".log", ".tmp", ".temp", ".swp", ".bak", ".lock",
}
SKIP_FILE_NAMES = {
    ".ds_store", "thumbs.db", "desktop.ini", ".env", "keys.env", "secrets.json",
    "credentials.json", "id_rsa", "id_ed25519", ".npmrc", ".pypirc", "token.txt",
    "api_key.txt", "apikey.txt",
}
SKIP_FILE_GLOBS = (".env.", "secret", "credential")

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}
DOC_EXT = {".pdf"}
CODE_EXT = {
    ".py", ".pyw", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".go", ".rs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".r", ".m", ".jl", ".lua", ".sql", ".sh", ".ps1", ".bat",
    ".html", ".htm", ".css", ".scss", ".vue", ".svelte", ".json", ".yml", ".yaml",
    ".toml", ".ini", ".cfg", ".md", ".txt", ".xml",
}
TEXT_SCANNABLE = CODE_EXT | {".env", ".conf", ".properties"}

MAX_FILE_BYTES = 45 * 1024 * 1024   # GitHub warns above 50 MB, hard-fails at 100 MB


def should_skip(path: Path) -> str | None:
    """Return a reason string when the file should not be published."""
    name = path.name.lower()
    if name in SKIP_FILE_NAMES:
        return "looks like a secrets file"
    if path.suffix.lower() in SKIP_FILE_EXT:
        return "build artefact"
    for frag in SKIP_FILE_GLOBS:
        if frag in name and path.suffix.lower() not in IMAGE_EXT:
            return "filename suggests credentials"
    if name.startswith("~$"):
        return "office lock file"
    return None


def walk_files(src: Path) -> list[Path]:
    """All publishable files under src (a file or a directory)."""
    if src.is_file():
        return [src]
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            found.append(Path(dirpath) / fn)
    return sorted(found)


# ---------------------------------------------------------------- secret scan

SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Stripe key", re.compile(r"\b[sr]k_(?:live|test)_[0-9a-zA-Z]{16,}\b")),
    ("OpenAI/Anthropic key", re.compile(r"\b(?:sk-ant-|sk-proj-|sk-)[A-Za-z0-9_\-]{20,}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("hard-coded credential",
     re.compile(r"""(?i)\b(?:api[_-]?key|apikey|secret|password|passwd|token|access[_-]?key)\b"""
                r"""\s*[:=]\s*["'][A-Za-z0-9_\-/+]{12,}["']""")),
]
SAFE_VALUE = re.compile(
    r"""(?i)["'](?:your|my|the|xxx+|placeholder|changeme|example|none|null|test|demo|"""
    r"""insert|todo|<[^>]*>|\$\{|os\.environ|getenv)""")


def scan_secrets(path: Path) -> list[tuple[int, str, str]]:
    """Return [(line_no, kind, excerpt)] of likely secrets in a text file."""
    if path.suffix.lower() not in TEXT_SCANNABLE:
        return []
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            return []
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    hits: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 600:
            continue
        for kind, pat in SECRET_PATTERNS:
            m = pat.search(line)
            if not m:
                continue
            if SAFE_VALUE.search(m.group(0)):
                continue
            excerpt = line.strip()
            if len(excerpt) > 110:
                excerpt = excerpt[:107] + "..."
            hits.append((lineno, kind, excerpt))
            break
    return hits


# ---------------------------------------------------------------- git

def git(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check, text=True,
        capture_output=capture, encoding="utf-8", errors="replace",
    )


def git_ok(*args: str) -> bool:
    try:
        return git(*args, check=False).returncode == 0
    except FileNotFoundError:
        return False


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def gh_path() -> str | None:
    """gh is not always on PATH right after winget installs it."""
    found = shutil.which("gh")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "GitHub CLI" / "gh.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "GitHub CLI" / "gh.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def open_url(url: str) -> None:
    try:
        if os.name == "nt":
            os.startfile(url)  # noqa: S606
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", url], check=False)
    except OSError:
        say(f"Open this yourself: {url}")
