#!/usr/bin/env python3
"""crr - deterministic helper for the acr-code-review skill.

Python 3.9+ standard library only. Run it from anywhere inside a git repository.
All review data lives in <repo>/.code-review/ and is meant to be committed.

Commands (all print JSON unless noted):
  init                      Create/upgrade .code-review/ (viewer, config, index).
  repo-stats [--sample N]   Size of the repo + explicit standard sources + sample files.
  context [--mode M]        Collect what to review. M: auto (default) | pending | full | branch.
                            Writes the diff to .code-review/.tmp/review.diff.
  apply RUN_JSON            Merge a review run (comments, updates, checks, summary,
                            standard_ops...) into the branch history and refresh the index.
  std OPS_JSON              Apply standard operations (add/update/activate/exceptions...).
  list [--status S] [--all] Comments of the current branch (or all branches). Plain text.
  show ID                   Full JSON of a comment (ACR-xxxxxx) or standard (STD-xxxx).
  standards [--status S]    Standards catalog. Plain text.
  config [options]          Show or change project settings (language, base, checks).
  index                     Rebuild data/index.js and the local view state.
"""
import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FORMAT_VERSION = 1
SKILL_DIR = Path(__file__).resolve().parent.parent
VIEWER_SRC = SKILL_DIR / "assets" / "viewer.html"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

CR = Path(".code-review")
DATA = CR / "data"
BRANCHES = DATA / "branches"
STDS = DATA / "standards"
STDLOG = DATA / "standards-log"
CONFIG = DATA / "config.js"
INDEX = DATA / "index.js"
TMP = CR / ".tmp"
VIEWER = CR / "index.html"
CONTEXT_FILE = TMP / "context.json"
DIFF_FILE = TMP / "review.diff"
LOCAL_FILE = TMP / "local.js"

SEVERITIES = ["critical", "major", "minor", "nitpick"]
BLOCKING_SEVERITIES = {"critical", "major"}
CATEGORIES = ["bug", "security", "performance", "maintainability", "style", "docs",
              "tests", "architecture", "other"]
COMMENT_STATUSES = ["open", "resolved", "dismissed", "excepted"]
CHECK_STATUSES = ["pass", "warn", "fail", "n/a"]
STD_LEVELS = ["required", "recommended", "preference"]
STD_STATUSES = ["proposed", "active", "deprecated", "rejected"]
STD_ORIGINS = ["explicit", "inferred", "user"]
STD_CATEGORIES = ["style", "naming", "structure", "architecture", "error-handling", "testing",
                  "libraries", "security", "performance", "docs", "git", "other"]
LEVEL_TO_SEVERITY = {"required": "major", "recommended": "minor", "preference": "nitpick"}

DEFAULT_CHECKS = [
    # id, group, name, blocking
    ("debug-code", "hygiene", "No leftover debug code", False),
    ("commented-code", "hygiene", "No commented-out code", False),
    ("todo-without-ticket", "hygiene", "No TODO/FIXME without a ticket reference", False),
    ("conflict-markers", "hygiene", "No unresolved merge conflict markers", True),
    ("unwanted-files", "hygiene", "No files that should not be committed (.env, keys, binaries, build output)", True),
    ("secrets", "security", "No secrets, keys or tokens", True),
    ("personal-data", "security", "No personal data in logs, fixtures or tests", False),
    ("new-dependencies", "security", "New dependencies are maintained, licensed and not redundant", False),
    ("missing-tests", "tests", "New logic is covered by tests", False),
    ("disabled-tests", "tests", "No skipped or focused tests (.skip/.only/@Disabled)", True),
    ("weakened-tests", "tests", "No deleted tests or weakened assertions", False),
    ("change-size", "shape", "Change size is reasonable for one commit", False),
    ("mixed-concerns", "shape", "Change does not mix unrelated concerns", False),
    ("format-noise", "shape", "No mass formatting mixed with logic changes", False),
    ("breaking-changes", "shape", "Breaking changes (API, contracts, schemas) are intentional and flagged", False),
    ("migrations", "shape", "Database migrations are reversible", False),
    ("undocumented-env", "docs", "New environment variables are documented", False),
    ("docs-not-updated", "docs", "API/config changes are reflected in docs/README/CHANGELOG", False),
]

EXPLICIT_SOURCES = [
    ".editorconfig", ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml",
    ".eslintrc.yaml", "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts",
    ".prettierrc", ".prettierrc.json", ".prettierrc.js", ".prettierrc.cjs", ".prettierrc.yml",
    "prettier.config.js", "prettier.config.cjs", "prettier.config.mjs", "biome.json", "biome.jsonc",
    "tsconfig.json", "jsconfig.json", ".stylelintrc", ".stylelintrc.json", "stylelint.config.js",
    "commitlint.config.js", "commitlint.config.cjs", "commitlint.config.ts", ".commitlintrc",
    ".commitlintrc.json", ".lintstagedrc", ".lintstagedrc.json", ".husky", "package.json",
    "pyproject.toml", "ruff.toml", ".ruff.toml", "setup.cfg", ".flake8", "tox.ini", "mypy.ini",
    ".pylintrc", ".golangci.yml", ".golangci.yaml", "rustfmt.toml", ".rustfmt.toml", "clippy.toml",
    ".rubocop.yml", "phpcs.xml", ".php-cs-fixer.php", "checkstyle.xml", ".swiftlint.yml",
    "CONTRIBUTING.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules", ".cursor/rules",
    ".github/copilot-instructions.md", ".github/pull_request_template.md", "ARCHITECTURE.md",
    "docs/ARCHITECTURE.md", "STYLEGUIDE.md", "docs/CONVENTIONS.md", "CONVENTIONS.md",
]

GENERATED_PATTERNS = [
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "poetry.lock", "Pipfile.lock",
    "uv.lock", "Cargo.lock", "composer.lock", "Gemfile.lock", "go.sum", "*.min.js", "*.min.css",
    "*.map", "*.snap", "dist/*", "build/*", "out/*", "coverage/*", "*/__snapshots__/*",
    "*.generated.*", "*.pb.go", "*_pb2.py",
]

HINT_PATTERNS = {
    "conflict-markers": re.compile(r"^(<{7}( |$)|={7}$|>{7}( |$))"),
    "debug-code": re.compile(
        r"console\.(log|debug|trace|dir)\s*\(|\bdebugger\b|\bpdb\.set_trace\(|\bbreakpoint\(\)|"
        r"\bvar_dump\(|\bdd\(|binding\.pry|System\.out\.println|\bfmt\.Println\(|\bprint\("),
    "todo-without-ticket": re.compile(r"\b(TODO|FIXME|XXX|HACK)\b"),
    "disabled-tests": re.compile(
        r"\b(it|describe|test|context)\.(only|skip)\s*\(|\bx(it|describe|test)\s*\(|\bf(it|describe)\s*\(|"
        r"@pytest\.mark\.skip|@unittest\.skip|@Ignore\b|@Disabled\b|\bt\.Skip\("),
}
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"\bsk-(live|test|proj|ant)?[-_]?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)"
               r"\b\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
]
UNWANTED_FILE_PATTERNS = [".env", "*/.env", ".env.*", "*/.env.*", "*.pem", "*.key", "*.p12", "*.pfx",
                          "id_rsa", "*/id_rsa", "*.DS_Store", "node_modules/*", "*.log", "*.sqlite",
                          "*.sqlite3", "*.db"]
UNWANTED_ALLOW = [".env.example", ".env.sample", ".env.template", "*/.env.example", "*/.env.sample"]


class CrrError(Exception):
    pass


# --------------------------------------------------------------------------------------- utils
def now_iso():
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def today():
    return dt.date.today().isoformat()


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def die(msg, **extra):
    out(dict({"error": msg}, **extra))
    sys.exit(1)


def git(args, env=None, check=True, input_text=None):
    r = subprocess.run(["git"] + list(args), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, input=input_text)
    if check and r.returncode != 0:
        raise CrrError("git {} failed: {}".format(" ".join(args), r.stderr.strip()))
    return r.stdout


def git_ok(args):
    return subprocess.run(["git"] + list(args), capture_output=True).returncode == 0


def git1(args):
    return git(args, check=False).strip()


def go_to_root():
    root = git1(["rev-parse", "--show-toplevel"])
    if not root:
        raise CrrError("Not inside a git work tree.")
    os.chdir(root)
    return root


def current_branch():
    name = git1(["symbolic-ref", "--quiet", "--short", "HEAD"])
    if name:
        return name
    head = git1(["rev-parse", "--short", "HEAD"])
    return "detached-" + (head or "nohead")


def slugify(branch):
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-.") or "branch"
    if slug != branch:
        slug += "--" + hashlib.sha1(branch.encode("utf-8")).hexdigest()[:6]
    return slug


def head_sha():
    return git1(["rev-parse", "--verify", "--quiet", "HEAD"]) or None


def tree_of(rev):
    if not rev:
        return EMPTY_TREE
    return git1(["rev-parse", "--verify", "--quiet", rev + "^{tree}"]) or EMPTY_TREE


def object_exists(sha):
    return bool(sha) and git_ok(["cat-file", "-e", sha])


def is_ancestor(a, b):
    return bool(a and b) and git_ok(["merge-base", "--is-ancestor", a, b])


def worktree_tree():
    """Tree object of the whole working tree (tracked + untracked, honouring .gitignore).

    Uses a throw-away index file, so the user's index, refs and stash are never touched.
    The resulting tree object is unreferenced (invisible in git log / branches).
    """
    tmpdir = tempfile.mkdtemp(prefix="crr-")
    idx = os.path.join(tmpdir, "index")
    try:
        real_index = git1(["rev-parse", "--git-path", "index"])
        if real_index and os.path.exists(real_index):
            shutil.copyfile(real_index, idx)  # keeps the stat cache -> fast
        env = dict(os.environ, GIT_INDEX_FILE=idx)
        if not os.path.exists(idx):
            h = head_sha()
            git(["read-tree", h] if h else ["read-tree", "--empty"], env=env)
        git(["add", "-A", "--", "."], env=env)
        return git(["write-tree"], env=env).strip()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


PATHSPEC = ["--", ".", ":(exclude).code-review"]


def diff_text(a, b):
    return git(["diff", "--no-color", "--no-ext-diff", "-M", "-U5", a, b] + PATHSPEC, check=False)


def diff_files(a, b):
    files = []
    raw = git(["diff", "--numstat", "--no-renames", "-z", a, b] + PATHSPEC, check=False)
    for rec in raw.split("\0"):
        if not rec.strip():
            continue
        parts = rec.split("\t", 2)
        if len(parts) < 3:
            continue
        add, dele, path = parts
        files.append({
            "path": path,
            "added": int(add) if add.isdigit() else None,
            "deleted": int(dele) if dele.isdigit() else None,
            "binary": add == "-",
            "generated": is_generated(path),
        })
    status = git(["diff", "--name-status", "--no-renames", a, b] + PATHSPEC, check=False)
    st = {}
    for line in status.splitlines():
        p = line.split("\t")
        if len(p) >= 2:
            st[p[-1]] = {"A": "added", "D": "deleted", "M": "modified", "T": "type-changed"}.get(p[0][0], "modified")
    for f in files:
        f["status"] = st.get(f["path"], "modified")
    return files


def match_any(path, patterns):
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def is_generated(path):
    base = path.rsplit("/", 1)[-1]
    return match_any(path, GENERATED_PATTERNS) or match_any(base, GENERATED_PATTERNS)


def path_matches(path, pattern):
    pattern = pattern.strip()
    if not pattern:
        return False
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return path == pattern or path.startswith(pattern.rstrip("/") + "/") or fnmatch.fnmatch(path, pattern)


def mask_secret(s):
    s = s.strip()
    if len(s) <= 8:
        return "***"
    return s[:4] + "…" + s[-3:]


# ------------------------------------------------------------------------------- data files
def write_data(path, kind, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(obj, indent=2, ensure_ascii=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text('CRR_LOAD("{}",\n{}\n);\n'.format(kind, body), encoding="utf-8")
    os.replace(tmp, path)


def read_data(path):
    txt = path.read_text(encoding="utf-8")
    if re.search(r"^(<{7}|>{7}|={7})", txt, re.M):
        raise CrrError("Unresolved git merge conflict in {}. Resolve it (keep the correct version) "
                       "and run the command again.".format(path))
    start = txt.index("\n") + 1
    end = txt.rstrip().rfind(");")
    return json.loads(txt[start:end])


def load_dir(d):
    items = []
    if d.exists():
        for p in sorted(d.glob("*.js")):
            items.append((p, read_data(p)))
    return items


def default_config():
    return {
        "format_version": FORMAT_VERSION,
        "language": "en",
        "base_branch": None,
        "checks": [{"id": i, "group": g, "name": n, "enabled": True, "blocking": b}
                   for i, g, n, b in DEFAULT_CHECKS],
        "created_at": now_iso(),
    }


def load_config():
    if not CONFIG.exists():
        return default_config()
    cfg = read_data(CONFIG)
    known = {c["id"] for c in cfg.get("checks", [])}
    for i, g, n, b in DEFAULT_CHECKS:  # new default checks appear after a skill upgrade
        if i not in known:
            cfg.setdefault("checks", []).append({"id": i, "group": g, "name": n, "enabled": True, "blocking": b})
    return cfg


def load_branch(slug, branch):
    p = BRANCHES / (slug + ".js")
    if p.exists():
        return read_data(p)
    return {
        "format_version": FORMAT_VERSION, "branch": branch, "slug": slug, "base": None,
        "created_at": now_iso(), "updated_at": now_iso(), "last_review": None,
        "summary": None, "walkthrough": None, "diagram": None, "effort": None,
        "commit_message": None, "checks_latest": [], "suggestions": [], "runs": [], "comments": [],
    }


def save_branch(b):
    b["updated_at"] = now_iso()
    write_data(BRANCHES / (b["slug"] + ".js"), "branch", b)


def load_standards():
    return {d["id"]: (p, d) for p, d in load_dir(STDS)}


def ensure_structure():
    created = not CR.exists()
    for d in (DATA, BRANCHES, STDS, STDLOG, TMP):
        d.mkdir(parents=True, exist_ok=True)
    gi = CR / ".gitignore"
    if not gi.exists():
        gi.write_text("# Local, per-worktree state (snapshots context, raw diffs, local view state)\n.tmp/\n",
                      encoding="utf-8")
    ga = CR / ".gitattributes"
    if not ga.exists():
        ga.write_text("# One entry per line: concurrent branches merge without conflicts\n"
                      "data/index.js merge=union\n", encoding="utf-8")
    if not CONFIG.exists():
        write_data(CONFIG, "config", default_config())
    viewer_updated = False
    if VIEWER_SRC.exists():
        src = VIEWER_SRC.read_bytes()
        if not VIEWER.exists() or VIEWER.read_bytes() != src:
            VIEWER.write_bytes(src)
            viewer_updated = True
    return created, viewer_updated


def rebuild_index():
    lines = []
    for sub in ("branches", "standards", "standards-log"):
        d = DATA / sub
        if d.exists():
            for p in sorted(d.glob("*.js")):
                lines.append('CRR_FILE("{}/{}");'.format(sub, p.name))
    INDEX.write_text("// Generated by crr.py - lists data files for the viewer. Safe to regenerate.\n"
                     + "\n".join(lines) + "\n", encoding="utf-8")
    TMP.mkdir(parents=True, exist_ok=True)
    branch = current_branch()
    local = {
        "repo": repo_name(),
        "current_branch": branch,
        "current_slug": slugify(branch),
        "local_branches": [b for b in git(["for-each-ref", "--format=%(refname:short)", "refs/heads"],
                                          check=False).splitlines() if b],
        "generated_at": now_iso(),
    }
    write_data(LOCAL_FILE, "local", local)


def repo_name():
    common = git1(["rev-parse", "--path-format=absolute", "--git-common-dir"])
    if common:
        p = Path(common)
        return (p.parent.name if p.name == ".git" else p.name.replace(".git", "")) or os.path.basename(os.getcwd())
    return os.path.basename(os.getcwd())


def detect_base(cfg, branch):
    cands = []
    if cfg.get("base_branch"):
        cands.append(cfg["base_branch"])
    ref = git1(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"])
    if ref:
        cands.append(ref.replace("refs/remotes/", ""))
    cands += ["main", "master", "develop", "origin/main", "origin/master", "origin/develop"]
    for c in cands:
        if c in (branch, "origin/" + branch) and not cfg.get("base_branch"):
            continue
        if git1(["rev-parse", "--verify", "--quiet", c]):
            return c
    return None


# ------------------------------------------------------------------------------------ hints
def scan_hints(diff, files):
    hints = {k: [] for k in list(HINT_PATTERNS) + ["secrets", "unwanted-files"]}
    cur, line_no = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            cur = raw[6:] if raw.startswith("+++ b/") else None
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
            continue
        if cur is None or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            text = raw[1:]
            for key, rx in HINT_PATTERNS.items():
                if rx.search(text) and len(hints[key]) < 50:
                    hints[key].append({"file": cur, "line": line_no, "text": text.strip()[:160]})
            for rx in SECRET_PATTERNS:
                m = rx.search(text)
                if m and len(hints["secrets"]) < 50:
                    masked = text.replace(m.group(0), mask_secret(m.group(0))).strip()[:160]
                    hints["secrets"].append({"file": cur, "line": line_no, "text": masked})
                    break
            line_no += 1
        elif not raw.startswith("-") and not raw.startswith("\\"):
            line_no += 1
    for f in files:
        p = f["path"]
        base = p.rsplit("/", 1)[-1]
        if f["status"] != "deleted" and not match_any(p, UNWANTED_ALLOW) and not match_any(base, UNWANTED_ALLOW):
            if match_any(p, UNWANTED_FILE_PATTERNS) or match_any(base, UNWANTED_FILE_PATTERNS):
                hints["unwanted-files"].append({"file": p, "reason": "matches a file type that is usually not committed"})
            elif f["binary"]:
                hints["unwanted-files"].append({"file": p, "reason": "binary file"})
    return {k: v for k, v in hints.items() if v}


# -------------------------------------------------------------------------------- standards
def exception_state(exc):
    exp = exc.get("expires")
    return "expired" if exp and exp < today() else "active"


def applicable_standards(stds, changed_paths):
    enforced, proposed = [], []
    for sid, (_, s) in sorted(stds.items()):
        scope = (s.get("scope") or {}).get("paths") or []
        in_scope = [p for p in changed_paths if not scope or any(path_matches(p, g) for g in scope)]
        if not in_scope:
            continue
        excepted = []
        for exc in s.get("exceptions", []):
            if exception_state(exc) == "active":
                excepted += [p for p in in_scope if path_matches(p, exc["path"])]
        entry = {
            "id": sid, "title": s.get("title"), "level": s.get("level"), "status": s.get("status"),
            "category": s.get("category"), "description": s.get("description"),
            "severity_if_violated": LEVEL_TO_SEVERITY.get(s.get("level"), "minor"),
            "applies_to": sorted(set(in_scope) - set(excepted)),
        }
        if excepted:
            entry["excepted_files"] = sorted(set(excepted))
        if s.get("status") == "deprecated":
            entry["note"] = ("Deprecated pattern: do not introduce it in new code; existing code is tolerated."
                             + (" Use {} instead.".format(s["replaced_by"]) if s.get("replaced_by") else ""))
        if s.get("status") in ("active", "deprecated") and entry["applies_to"]:
            enforced.append(entry)
        elif s.get("status") == "proposed":
            proposed.append({"id": sid, "title": s.get("title")})
    return enforced, proposed


def standards_alerts(stds, all_branches):
    alerts = {"proposed": [], "divergent": [], "expired_exceptions": [], "drift": []}
    for sid, (_, s) in sorted(stds.items()):
        if s.get("status") == "proposed":
            alerts["proposed"].append({"id": sid, "title": s.get("title")})
        if s.get("divergence") and s.get("status") in ("active", "deprecated"):
            alerts["divergent"].append({"id": sid, "title": s.get("title"),
                                        "source": (s.get("source") or {}).get("file"),
                                        "note": s["divergence"].get("note")})
        for exc in s.get("exceptions", []):
            if exception_state(exc) == "expired":
                alerts["expired_exceptions"].append({"id": sid, "path": exc["path"], "expired_on": exc["expires"]})
    # drift: violations of one standard repeated across recent review runs
    recent = []
    for b in all_branches:
        for r in b.get("runs", []):
            if r.get("kind") != "status":
                recent.append((r.get("at", ""), b["slug"], r["n"]))
    recent = set((s, n) for _, s, n in sorted(recent)[-15:])
    hits, dismissed = {}, {}
    for b in all_branches:
        for c in b.get("comments", []):
            sid = c.get("standard")
            if not sid or (b["slug"], c.get("created_run")) not in recent:
                continue
            hits.setdefault(sid, set()).add((b["slug"], c.get("created_run")))
            if c.get("status") == "dismissed":
                dismissed[sid] = dismissed.get(sid, 0) + 1
    for sid, runs in hits.items():
        if sid in stds and (len(runs) >= 3 or dismissed.get(sid, 0) >= 2):
            alerts["drift"].append({
                "id": sid, "title": stds[sid][1].get("title"), "runs_with_violations": len(runs),
                "dismissed": dismissed.get(sid, 0),
                "suggestion": "Repeated violations/dismissals: ask the user whether this standard still "
                              "reflects how they work (re-analyze or adjust it).",
            })
    return {k: v for k, v in alerts.items() if v}


def new_id(prefix, nbytes, taken):
    while True:
        i = prefix + secrets.token_hex(nbytes)
        if i not in taken:
            return i


def log_event(sid, action, reason="", details=None, branch=None, run=None):
    now = dt.datetime.now()
    name = "{}-{}-{}.js".format(now.strftime("%Y%m%dT%H%M%S%f"), sid, secrets.token_hex(2))
    write_data(STDLOG / name, "stdlog", {
        "at": now_iso(), "seq": now.strftime("%Y%m%dT%H%M%S%f"), "standard": sid, "action": action, "reason": reason or "",
        "details": details or {}, "branch": branch, "run": run,
    })


def clean_standard_fields(fields, warnings, sid="new"):
    f = dict(fields)
    if "level" in f and f["level"] not in STD_LEVELS:
        warnings.append("{}: invalid level {!r}, using 'recommended'".format(sid, f["level"]))
        f["level"] = "recommended"
    if "status" in f and f["status"] not in STD_STATUSES:
        warnings.append("{}: invalid status {!r}, using 'proposed'".format(sid, f["status"]))
        f["status"] = "proposed"
    if "origin" in f and f["origin"] not in STD_ORIGINS:
        f["origin"] = "inferred"
    if "category" in f and f["category"] not in STD_CATEGORIES:
        f["category"] = "other"
    if "scope" in f and isinstance(f["scope"], list):
        f["scope"] = {"paths": f["scope"]}
    for k in ("id", "exceptions", "created_at", "history"):
        f.pop(k, None)
    return f


def apply_standard_ops(ops, branch=None, run=None):
    stds = load_standards()
    results, warnings = [], []
    for op in ops or []:
        kind = op.get("op")
        sid = op.get("id")
        reason = op.get("reason", "")
        if kind == "add":
            s = clean_standard_fields(op.get("standard") or {}, warnings)
            if not s.get("title"):
                warnings.append("add: missing title, skipped")
                continue
            sid = new_id("STD-", 2, set(stds))
            s = dict({"id": sid, "title": "", "description": "", "category": "other", "level": "recommended",
                      "status": "proposed", "origin": "inferred", "source": None, "scope": {"paths": []},
                      "examples": [], "prevalence": None, "rationale": "", "replaced_by": None,
                      "divergence": None, "migration": None, "exceptions": [],
                      "created_at": now_iso()}, **s)
            s["id"] = sid
            s["updated_at"] = now_iso()
            write_data(STDS / (sid + ".js"), "standard", s)
            stds[sid] = (STDS / (sid + ".js"), s)
            log_event(sid, "created", reason, {"status": s["status"], "level": s["level"], "origin": s["origin"]},
                      branch, run)
            results.append({"op": "add", "id": sid, "title": s["title"], "status": s["status"]})
            continue
        if sid not in stds:
            warnings.append("{}: unknown standard {!r}".format(kind, sid))
            continue
        path, s = stds[sid]
        details = {}
        if kind == "update":
            fields = clean_standard_fields(op.get("fields") or {}, warnings, sid)
            for k, v in fields.items():
                if s.get(k) != v:
                    details[k] = {"from": s.get(k), "to": v}
                    s[k] = v
            action = "updated"
            if s.get("origin") == "explicit" and any(k in details for k in ("level", "description", "title", "scope")):
                if not op.get("source_updated"):
                    s["divergence"] = {"note": op.get("divergence_note") or
                                       "Changed here but the original source ({}) still says otherwise.".format(
                                           (s.get("source") or {}).get("file", "source")),
                                       "since": now_iso()}
                    details["divergence"] = "flagged"
        elif kind == "activate":
            details = {"status": {"from": s["status"], "to": "active"}}
            s["status"], action = "active", "activated"
        elif kind == "reject":
            details = {"status": {"from": s["status"], "to": "rejected"}}
            s["status"], action = "rejected", "rejected"
        elif kind == "deprecate":
            details = {"status": {"from": s["status"], "to": "deprecated"}, "replaced_by": op.get("replaced_by")}
            s["status"], s["replaced_by"], action = "deprecated", op.get("replaced_by"), "deprecated"
        elif kind == "add_exception":
            if not op.get("path") or not reason:
                warnings.append("{}: add_exception needs 'path' and 'reason'".format(sid))
                continue
            exp = op.get("expires")
            if exp and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(exp)):
                warnings.append("{}: expires must be YYYY-MM-DD, ignored".format(sid))
                exp = None
            s.setdefault("exceptions", [])
            s["exceptions"] = [e for e in s["exceptions"] if e["path"] != op["path"]]
            s["exceptions"].append({"path": op["path"], "reason": reason, "expires": exp,
                                    "created_at": now_iso(), "branch": branch})
            details, action = {"path": op["path"], "expires": exp}, "exception_added"
        elif kind == "remove_exception":
            before = len(s.get("exceptions", []))
            s["exceptions"] = [e for e in s.get("exceptions", []) if e["path"] != op.get("path")]
            if len(s["exceptions"]) == before:
                warnings.append("{}: no exception for {!r}".format(sid, op.get("path")))
                continue
            details, action = {"path": op.get("path")}, "exception_removed"
        elif kind == "flag_divergence":
            s["divergence"] = {"note": op.get("note") or reason, "since": now_iso()}
            details, action = {"note": s["divergence"]["note"]}, "divergence_flagged"
        elif kind == "resolve_divergence":
            s["divergence"] = None
            details, action = {"note": op.get("note") or reason}, "divergence_resolved"
        elif kind == "record_migration":
            s["migration"] = {"remaining": int(op.get("remaining", 0)), "measured_at": now_iso(),
                              "note": op.get("note", "")}
            details, action = dict(s["migration"]), "migration_measured"
        else:
            warnings.append("unknown op {!r}".format(kind))
            continue
        s["updated_at"] = now_iso()
        write_data(path, "standard", s)
        log_event(sid, action, reason, details, branch, run)
        results.append({"op": kind, "id": sid})
    return results, warnings


# ---------------------------------------------------------------------------------- commands
def cmd_init(a):
    go_to_root()
    created, viewer_updated = ensure_structure()
    rebuild_index()
    stds = load_standards()
    out({
        "initialized": True, "created_now": created, "viewer_updated": viewer_updated,
        "panel": str(VIEWER.resolve()), "standards": len(stds),
        "needs_initial_analysis": len(stds) == 0,
        "language": load_config().get("language"),
    })


def cmd_repo_stats(a):
    go_to_root()
    files = [f for f in git(["ls-files", "-z"]).split("\0") if f and not f.startswith(".code-review/")]
    src = [f for f in files if not is_generated(f)]
    by_dir, by_ext = {}, {}
    for f in src:
        top = f.split("/", 1)[0] if "/" in f else "(root)"
        by_dir[top] = by_dir.get(top, 0) + 1
        ext = os.path.splitext(f)[1].lower() or "(none)"
        by_ext[ext] = by_ext.get(ext, 0) + 1
    sources = []
    for s in EXPLICIT_SOURCES:
        if Path(s).exists():
            sources.append(s + ("/" if Path(s).is_dir() else ""))
    sample = []
    n = max(1, a.sample)
    groups = {}
    for f in src:
        groups.setdefault(f.rsplit("/", 1)[0] if "/" in f else "(root)", []).append(f)
    for d, fs in sorted(groups.items()):
        step = max(1, len(fs) // n)
        sample += fs[::step][:n]
    size = len(src)
    out({
        "tracked_files": len(files), "source_files": size,
        "suggested_scope": "full" if size <= 400 else ("sample" if size <= 5000 else "on-demand"),
        "by_top_dir": dict(sorted(by_dir.items(), key=lambda x: -x[1])),
        "by_extension": dict(sorted(by_ext.items(), key=lambda x: -x[1])[:20]),
        "explicit_sources": sources,
        "sample_files": sample[:400],
    })


def cmd_context(a):
    go_to_root()
    ensure_structure()
    cfg = load_config()
    branch = current_branch()
    slug = slugify(branch)
    b = load_branch(slug, branch)
    stds = load_standards()
    all_branches = [d for _, d in load_dir(BRANCHES)]

    head = head_sha()
    head_tree = tree_of(head)
    cur_tree = worktree_tree()
    base = detect_base(cfg, branch)
    merge_base = git1(["merge-base", base, "HEAD"]) if base and head else ""
    prev = b.get("last_review") or {}
    snapshot = prev.get("snapshot")
    snapshot_ok = object_exists(snapshot)
    pending_changed = cur_tree != head_tree
    attention = []

    commits_ahead = []
    if merge_base:
        for line in git(["log", "--format=%h%x09%s", "{}..HEAD".format(merge_base)], check=False).splitlines():
            h, _, subj = line.partition("\t")
            commits_ahead.append({"sha": h, "subject": subj})

    history_rewritten = bool(prev.get("head")) and bool(head) and not is_ancestor(prev["head"], head)
    base_moved = bool(prev.get("merge_base")) and bool(merge_base) and prev["merge_base"] != merge_base

    mode = a.mode
    from_ref = None
    if mode == "auto":
        if snapshot_ok:
            mode, from_ref = "incremental", snapshot
        else:
            mode, from_ref = "pending", head_tree
            if prev and snapshot and not snapshot_ok:
                attention.append("The previous review snapshot is not available on this machine (or was "
                                 "garbage-collected): reviewing all pending changes and re-verifying every open comment.")
    elif mode in ("pending", "full"):
        from_ref = head_tree
    elif mode == "branch":
        from_ref = tree_of(merge_base) if merge_base else EMPTY_TREE
        if not merge_base:
            attention.append("No base branch found; reviewing the whole tree. Ask the user for the base "
                             "branch and set it with `config --base`.")
    else:
        raise CrrError("Unknown mode " + mode)

    unreviewed_commits = []
    if mode == "incremental":
        if history_rewritten or base_moved:
            attention.append("Branch history was rewritten or the base moved since the last review (rebase?). "
                             "The incremental diff may include upstream code. Offer the user a branch review "
                             "(`context --mode branch`).")
        # Commits made after the last review whose content differs from what was reviewed.
        if prev.get("head") and head and prev["head"] != head and not history_rewritten:
            touched = [f for f in git(["diff", "--name-only", prev["head"], head] + PATHSPEC,
                                      check=False).splitlines() if f]
            differing = [f for f in git(["diff", "--name-only", snapshot, head_tree, "--"] + touched,
                                        check=False).splitlines() if f] if touched else []
            if differing:
                for line in git(["log", "--format=%h%x09%s", "{}..HEAD".format(prev["head"]), "--"] + differing,
                                check=False).splitlines():
                    h, _, subj = line.partition("\t")
                    # a commit whose content equals the reviewed snapshot was reviewed before committing
                    if git_ok(["diff", "--quiet", snapshot, tree_of(h)] + PATHSPEC):
                        continue
                    unreviewed_commits.append({"sha": h, "subject": subj})
                attention.append("Commits made after the last review contain changes that were never reviewed "
                                 "({} file(s)). They are included in this incremental diff. Ask the user whether "
                                 "to include them; if not, rerun with `--mode pending`.".format(len(differing)))
    elif mode in ("pending", "full") and not prev and commits_ahead and not pending_changed:
        attention.append("Nothing pending, but the branch has {} commit(s) never reviewed. Offer a branch "
                         "review (`context --mode branch`).".format(len(commits_ahead)))
    elif mode in ("pending", "full") and not prev and commits_ahead:
        attention.append("This branch has {} earlier commit(s) never reviewed. Ask the user whether to "
                         "include them (`context --mode branch`) or review only pending changes.".format(len(commits_ahead)))

    diff = diff_text(from_ref, cur_tree)
    files = diff_files(from_ref, cur_tree)
    DIFF_FILE.write_text(diff, encoding="utf-8")
    nothing = not files

    offers = []
    if nothing:
        if mode == "incremental" and pending_changed:
            offers.append("Nothing changed since the last review. Offer a full re-review of pending changes "
                          "(`--mode full`) if the user wants a second look.")
        elif not pending_changed and (commits_ahead or mode == "incremental"):
            offers.append("No pending changes and nothing new since the last review. Offer a branch review "
                          "(`--mode branch`).")
        else:
            offers.append("Nothing to review.")

    changed_paths = [f["path"] for f in files if f["status"] != "deleted"]
    enforced, proposed = applicable_standards(stds, changed_paths)
    open_comments = [
        {k: c.get(k) for k in ("id", "severity", "category", "file", "line_start", "line_end", "title", "standard")}
        for c in b.get("comments", []) if c.get("status") == "open"
    ]
    checks = [{"id": c["id"], "group": c["group"], "name": c["name"], "blocking": c["blocking"]}
              for c in cfg.get("checks", []) if c.get("enabled", True)]

    ctx = {
        "branch": branch, "slug": slug, "mode": mode, "head": head, "base": base,
        "merge_base": merge_base or None, "snapshot": cur_tree, "from": from_ref, "at": now_iso(),
        "files": len(files),
    }
    CONTEXT_FILE.write_text(json.dumps(ctx, indent=2), encoding="utf-8")

    out({
        "repo_root": os.getcwd(),
        "branch": branch, "base": base, "mode": mode,
        "language": cfg.get("language", "en"),
        "first_review_of_branch": not b.get("runs"),
        "nothing_to_review": nothing, "offers": offers,
        "attention": attention,
        "diff_file": str(DIFF_FILE), "diff_lines": diff.count("\n"),
        "files": files,
        "totals": {"files": len(files), "added": sum(f["added"] or 0 for f in files),
                   "deleted": sum(f["deleted"] or 0 for f in files)},
        "pending_changes": pending_changed,
        "commits_ahead_of_base": commits_ahead[:50],
        "unreviewed_commits": unreviewed_commits,
        "open_comments": open_comments,
        "standards_enforced": enforced,
        "standards_proposed_not_enforced": proposed,
        "standards_catalog_size": len(stds),
        "needs_initial_analysis": len(stds) == 0,
        "checks": checks,
        "hints": scan_hints(diff, files) if files else {},
        "alerts": standards_alerts(stds, all_branches),
        "previous_branch_content": {k: b.get(k) for k in ("summary", "walkthrough", "diagram", "effort")}
        if b.get("summary") else None,
    })


def norm_title(t):
    return re.sub(r"\s+", " ", str(t or "")).strip().lower()


def cmd_apply(a):
    run_path = Path(a.run_file).resolve()
    go_to_root()
    ensure_structure()
    run = json.loads(run_path.read_text(encoding="utf-8"))
    cfg = load_config()
    branch = current_branch()
    slug = slugify(branch)
    b = load_branch(slug, branch)
    stds = load_standards()
    warnings = []

    ctx = None
    if CONTEXT_FILE.exists():
        ctx = json.loads(CONTEXT_FILE.read_text(encoding="utf-8"))
        if ctx.get("slug") != slug:
            warnings.append("Ignoring context from another branch ({}).".format(ctx.get("branch")))
            ctx = None
    if ctx is not None:
        try:
            age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(ctx["at"])
            if age.total_seconds() > 12 * 3600:
                warnings.append("Ignoring a stale review context (older than 12h). Run `context` again to review.")
                ctx = None
        except (KeyError, ValueError):
            ctx = None
    looks_like_review = any(k in run for k in ("checks", "new_comments", "summary"))
    is_review = ctx is not None and not run.get("status_only") and looks_like_review
    kind = ctx["mode"] if is_review else "status"
    n = len(b["runs"]) + 1

    taken = set()
    for _, other in load_dir(BRANCHES):
        taken |= {c["id"] for c in other.get("comments", [])}
    by_id = {c["id"]: c for c in b["comments"]}
    by_fp = {(c["file"], norm_title(c["title"])): c for c in b["comments"]}
    counts = {"new": 0, "resolved": 0, "dismissed": 0, "excepted": 0, "reopened": 0, "updated": 0}

    # 1. standard operations first (comments may reference new standards)
    std_results, std_warn = apply_standard_ops(run.get("standard_ops"), branch, n)
    warnings += std_warn
    stds = load_standards()

    # 2. updates of existing comments
    editable = ("file", "line_start", "line_end", "body", "suggestion", "agent_prompt", "severity",
                "category", "title", "standard")
    for u in run.get("updates", []):
        c = by_id.get(u.get("id"))
        if not c:
            warnings.append("update for unknown comment {!r} ignored (comments of other branches cannot be "
                            "changed from here)".format(u.get("id")))
            continue
        old, new = c.get("status", "open"), u.get("status", c.get("status", "open"))
        if new not in COMMENT_STATUSES:
            warnings.append("{}: invalid status {!r}".format(c["id"], new))
            new = old
        if new in ("dismissed", "excepted") and not u.get("note"):
            warnings.append("{}: a reason ('note') is required to {} a comment".format(c["id"], new))
            continue
        if new == "excepted" and not c.get("standard"):
            warnings.append("{}: comment has no standard; recorded as 'dismissed' instead of 'excepted'".format(c["id"]))
            new = "dismissed"
        for f in editable:
            if f in u:
                c[f] = u[f]
        if u.get("note"):
            c["resolution"] = u["note"]
        c["status"] = new
        if old == "open" and new != "open":
            c["closed_run"], c["closed_at"] = n, now_iso()
            counts[new] += 1
        elif old != "open" and new == "open":
            c.pop("closed_run", None)
            c.pop("closed_at", None)
            counts["reopened"] += 1
        else:
            counts["updated"] += 1

    # 3. new comments
    for nc in run.get("new_comments", []):
        missing = [k for k in ("file", "title", "severity", "body") if not nc.get(k)]
        if missing:
            warnings.append("new comment {!r} skipped: missing {}".format(nc.get("title"), missing))
            continue
        c = {k: nc.get(k) for k in ("file", "line_start", "line_end", "severity", "category", "title", "body",
                                     "suggestion", "agent_prompt", "standard")}
        if c["severity"] not in SEVERITIES:
            warnings.append("{!r}: invalid severity {!r}, using 'minor'".format(c["title"], c["severity"]))
            c["severity"] = "minor"
        if c.get("category") not in CATEGORIES:
            c["category"] = "other"
        for k in ("line_start", "line_end"):
            try:
                c[k] = int(c[k]) if c.get(k) is not None else None
            except (TypeError, ValueError):
                c[k] = None
        if c["line_start"] and not c["line_end"]:
            c["line_end"] = c["line_start"]
        if c.get("standard") and c["standard"] not in stds:
            warnings.append("{!r}: unknown standard {!r} removed".format(c["title"], c["standard"]))
            c["standard"] = None
        fp = (c["file"], norm_title(c["title"]))
        if fp in by_fp:
            ex = by_fp[fp]
            was = ex.get("status")
            ex.update({k: v for k, v in c.items() if v is not None})
            if was != "open":
                ex["status"] = "open"
                ex.pop("closed_run", None)
                ex.pop("closed_at", None)
                counts["reopened"] += 1
            else:
                counts["updated"] += 1
            continue
        c["id"] = new_id("ACR-", 3, taken)
        taken.add(c["id"])
        c.update({"status": "open", "created_run": n, "created_at": now_iso()})
        b["comments"].append(c)
        by_id[c["id"]] = c
        by_fp[fp] = c
        counts["new"] += 1

    # 4. branch-level content (replaced when sent)
    for k in ("summary", "walkthrough", "diagram", "effort", "commit_message"):
        if k in run:
            b[k] = run[k]
    if "suggestions" in run:
        b["suggestions"] = [{"text": s, "run": n} for s in run.get("suggestions") or []]

    # 5. checks
    enabled = {c["id"]: c for c in cfg.get("checks", []) if c.get("enabled", True)}
    if is_review:
        results = []
        for ch in run.get("checks", []):
            if ch.get("id") not in enabled:
                warnings.append("unknown or disabled check {!r} ignored".format(ch.get("id")))
                continue
            st = ch.get("status")
            if st not in CHECK_STATUSES:
                warnings.append("check {}: invalid status {!r}".format(ch["id"], st))
                continue
            results.append({"id": ch["id"], "status": st, "note": ch.get("note", "")})
        reported = {r["id"] for r in results}
        missing_checks = [i for i in enabled if i not in reported]
        if missing_checks:
            warnings.append("checks not reported (recorded as n/a): {}".format(", ".join(missing_checks)))
            results += [{"id": i, "status": "n/a", "note": "not evaluated"} for i in missing_checks]
        b["checks_latest"] = results

    # 6. verdict
    open_c = [c for c in b["comments"] if c.get("status") == "open"]
    blocking_comments = [c for c in open_c if c["severity"] in BLOCKING_SEVERITIES]
    blocking_checks = [r for r in b.get("checks_latest", [])
                       if r["status"] == "fail" and enabled.get(r["id"], {}).get("blocking")]
    blockers = len(blocking_comments) + len(blocking_checks)
    verdict = "ready" if blockers == 0 else "blocked"

    record = {
        "n": n, "at": now_iso(), "kind": kind, "head": (ctx or {}).get("head") or head_sha(),
        "verdict": verdict, "blockers": blockers, "counts": counts,
        "open_after": {s: sum(1 for c in open_c if c["severity"] == s) for s in SEVERITIES},
        "agent": run.get("agent", ""), "note": run.get("note", ""),
    }
    if is_review:
        record["checks"] = b["checks_latest"]
        record["files_reviewed"] = ctx.get("files", 0)
        b["last_review"] = {"head": ctx.get("head"), "snapshot": ctx.get("snapshot"),
                            "merge_base": ctx.get("merge_base"), "base": ctx.get("base"), "at": now_iso()}
        b["base"] = ctx.get("base")
        CONTEXT_FILE.unlink()
    b["runs"].append(record)
    b["verdict"] = verdict
    save_branch(b)
    rebuild_index()

    out({
        "run": n, "kind": kind, "verdict": verdict, "blockers": blockers,
        "blocking_comments": [{"id": c["id"], "severity": c["severity"], "title": c["title"],
                               "where": "{}:{}".format(c["file"], c.get("line_start") or "")} for c in blocking_comments],
        "blocking_checks": [{"id": r["id"], "note": r.get("note", "")} for r in blocking_checks],
        "counts": counts, "open_by_severity": record["open_after"],
        "standard_ops": std_results,
        "panel": str(VIEWER.resolve()),
        "remember": "Review data changed under .code-review/ - remind the user to include it in the commit.",
        "warnings": warnings,
    })


def cmd_std(a):
    ops_path = Path(a.ops_file).resolve()
    go_to_root()
    ensure_structure()
    data = json.loads(ops_path.read_text(encoding="utf-8"))
    ops = data.get("standard_ops", data) if isinstance(data, dict) else data
    results, warnings = apply_standard_ops(ops, current_branch(), None)
    rebuild_index()
    out({"results": results, "warnings": warnings, "standards": len(load_standards())})


def loc(c):
    s = c["file"]
    if c.get("line_start"):
        s += ":{}".format(c["line_start"])
        if c.get("line_end") and c["line_end"] != c["line_start"]:
            s += "-{}".format(c["line_end"])
    return s


def cmd_list(a):
    go_to_root()
    branches = [d for _, d in load_dir(BRANCHES)]
    slug = slugify(current_branch())
    if not a.all:
        branches = [b for b in branches if b["slug"] == slug]
    for b in branches:
        rows = [c for c in b.get("comments", []) if a.status == "all" or c.get("status") == a.status]
        if not rows:
            continue
        print("# {}  (verdict: {})".format(b["branch"], b.get("verdict", "-")))
        for c in sorted(rows, key=lambda c: (SEVERITIES.index(c["severity"]), c["file"])):
            std = " [{}]".format(c["standard"]) if c.get("standard") else ""
            print("{}  {:<9} {:<8} {}  {}{}".format(c["id"], c["status"], c["severity"], loc(c), c["title"], std))


def cmd_show(a):
    go_to_root()
    if a.id.startswith("STD-"):
        stds = load_standards()
        if a.id in stds:
            log = [d for _, d in load_dir(STDLOG) if d.get("standard") == a.id]
            return out(dict(stds[a.id][1], log=log))
    else:
        for _, b in load_dir(BRANCHES):
            for c in b.get("comments", []):
                if c["id"] == a.id:
                    return out(dict(c, branch=b["branch"]))
    die("not found: " + a.id)


def cmd_standards(a):
    go_to_root()
    for sid, (_, s) in sorted(load_standards().items(), key=lambda x: (STD_STATUSES.index(x[1][1].get("status", "proposed")), x[0])):
        if a.status != "all" and s.get("status") != a.status:
            continue
        flags = []
        if s.get("divergence"):
            flags.append("DIVERGENT")
        if s.get("exceptions"):
            flags.append("{} exc".format(len(s["exceptions"])))
        print("{}  {:<10} {:<11} {:<14} {}{}".format(sid, s.get("status"), s.get("level"), s.get("category"),
                                                    s.get("title"), "  (" + ", ".join(flags) + ")" if flags else ""))


def cmd_config(a):
    go_to_root()
    ensure_structure()
    cfg = load_config()
    changed = False
    if a.language:
        cfg["language"], changed = a.language, True
    if a.base is not None:
        cfg["base_branch"], changed = (a.base or None), True
    if a.check:
        ch = next((c for c in cfg["checks"] if c["id"] == a.check), None)
        if not ch:
            die("unknown check " + a.check, checks=[c["id"] for c in cfg["checks"]])
        if a.enabled is not None:
            ch["enabled"] = a.enabled == "true"
        if a.blocking is not None:
            ch["blocking"] = a.blocking == "true"
        changed = True
    if changed:
        write_data(CONFIG, "config", cfg)
    out(cfg)


def cmd_index(a):
    go_to_root()
    ensure_structure()
    rebuild_index()
    out({"index": str(INDEX), "panel": str(VIEWER.resolve())})


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(func=cmd_init)
    s = sub.add_parser("repo-stats")
    s.add_argument("--sample", type=int, default=5, help="files per directory in the sample")
    s.set_defaults(func=cmd_repo_stats)
    s = sub.add_parser("context")
    s.add_argument("--mode", default="auto", choices=["auto", "pending", "full", "branch"])
    s.set_defaults(func=cmd_context)
    s = sub.add_parser("apply")
    s.add_argument("run_file")
    s.set_defaults(func=cmd_apply)
    s = sub.add_parser("std")
    s.add_argument("ops_file")
    s.set_defaults(func=cmd_std)
    s = sub.add_parser("list")
    s.add_argument("--status", default="open", choices=COMMENT_STATUSES + ["all"])
    s.add_argument("--all", action="store_true", help="all branches")
    s.set_defaults(func=cmd_list)
    s = sub.add_parser("show")
    s.add_argument("id")
    s.set_defaults(func=cmd_show)
    s = sub.add_parser("standards")
    s.add_argument("--status", default="all", choices=STD_STATUSES + ["all"])
    s.set_defaults(func=cmd_standards)
    s = sub.add_parser("config")
    s.add_argument("--language")
    s.add_argument("--base", help="base branch (empty string = auto-detect)")
    s.add_argument("--check")
    s.add_argument("--enabled", choices=["true", "false"])
    s.add_argument("--blocking", choices=["true", "false"])
    s.set_defaults(func=cmd_config)
    sub.add_parser("index").set_defaults(func=cmd_index)
    a = p.parse_args()
    try:
        a.func(a)
    except CrrError as e:
        die(str(e))


if __name__ == "__main__":
    main()
