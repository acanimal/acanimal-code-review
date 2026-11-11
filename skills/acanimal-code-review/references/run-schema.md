# Run JSON and standard operations

Write the file under `.code-review/.tmp/` and pass it to `CRR apply <file>`. Every key is optional.

## Review run

A run is recorded as a **review** when a context from `CRR context` is pending for this branch and the run contains `checks`, `new_comments` or `summary`. Otherwise (or with `"status_only": true`) it is a **status** run: only updates and standard ops, no snapshot.

```jsonc
{
  "agent": "claude-code", // claude-code | opencode | cursor | ...
  "note": "Optional note shown in the timeline",
  "status_only": false,

  // Branch content: replaces the stored value when present (describe the whole branch)
  "summary": {
    "text": "markdown",
    "highlights": [
      {
        "type": "feature|fix|refactor|perf|security|docs|test|chore|breaking",
        "text": "...",
      },
    ],
  },
  "walkthrough": {
    "overview": "markdown",
    "changes": [
      {
        "cohort": "API",
        "files": ["src/routes/users.ts"],
        "summary": "markdown",
      },
    ],
  },
  "diagram": "sequenceDiagram\n  A->>B: call", // omit when not useful
  "effort": { "score": 2, "minutes": 10, "reason": "..." },
  "commit_message": "feat(users): add search endpoint\n\nOptional body",
  "suggestions": ["Short note for the user, e.g. a possible new standard"],

  // Every enabled check from context.checks
  "checks": [
    {
      "id": "secrets",
      "status": "pass|warn|fail|n/a",
      "note": "required when not pass",
    },
  ],

  "new_comments": [
    {
      "file": "src/routes/users.ts", // required, repo-relative
      "line_start": 42,
      "line_end": 48, // current version of the file
      "severity": "critical|major|minor|nitpick", // required
      "category": "bug|security|performance|maintainability|style|docs|tests|architecture|other",
      "title": "One specific line", // required; file+title de-duplicates
      "body": "markdown: problem, impact, fix", // required
      "suggestion": "  context\n-old\n+new",
      "agent_prompt": "Self-contained instruction for a coding agent",
      "standard": "STD-1a2b", // when it violates a standard
    },
  ],

  "updates": [
    {
      "id": "ACR-1a2b3c", // comment of THIS branch
      "status": "open|resolved|dismissed|excepted",
      "note": "Reason (required for dismissed/excepted)",
      "line_start": 50,
      "line_end": 55, // optional: also title, body, severity, category, suggestion, agent_prompt, standard
    },
  ],

  "standard_ops": [
    /* see below; applied before comments */
  ],
}
```

The script computes the verdict: **blocked** if any open `critical`/`major` comment or any blocking check with `fail`; otherwise **ready**. Checks not reported are stored as `n/a` with a warning.

## Standard operations

Used in `standard_ops` of a run or in a file passed to `CRR std` (either a list or `{"standard_ops": [...]}`). Every op accepts `"reason"`; it is stored in the standards changelog.

```jsonc
// Create (id is assigned: STD-xxxx)
{"op": "add", "reason": "Found in .eslintrc", "standard": {
  "title": "Use the shared logger instead of console",
  "description": "markdown: the rule, why, and a short good/bad example",
  "category": "style|naming|structure|architecture|error-handling|testing|libraries|security|performance|docs|git|other",
  "level": "required|recommended|preference",
  "status": "active|proposed",            // explicit → active, inferred → proposed, user-stated → active
  "origin": "explicit|inferred|user",
  "source": {"file": ".eslintrc.json", "detail": "rule no-console"},   // explicit only
  "scope": {"paths": ["src/**"]},          // empty = whole repo
  "examples": [{"file": "src/services/user.ts", "note": "follows it"}],
  "prevalence": "42/45 services",          // inferred only
  "rationale": "why"
}}

{"op": "update", "id": "STD-1a2b", "fields": {"level": "required"}, "reason": "...",
 "source_updated": false}                  // explicit standards: true only if the source file was edited too
{"op": "activate", "id": "STD-1a2b", "reason": "validated by the user"}
{"op": "reject", "id": "STD-1a2b", "reason": "..."}
{"op": "deprecate", "id": "STD-1a2b", "replaced_by": "STD-9f8e", "reason": "migrating to the new HTTP client"}
{"op": "add_exception", "id": "STD-1a2b", "path": "src/legacy/", "reason": "legacy code, migrated in Q2",
 "expires": "2027-03-01"}                  // path: file, directory (trailing /) or glob; reason required
{"op": "remove_exception", "id": "STD-1a2b", "path": "src/legacy/", "reason": "..."}
{"op": "flag_divergence", "id": "STD-1a2b", "note": "CONTRIBUTING.md still says X"}
{"op": "resolve_divergence", "id": "STD-1a2b", "note": "CONTRIBUTING.md updated"}
{"op": "record_migration", "id": "STD-1a2b", "remaining": 17, "note": "grep for axios imports"}
```

Notes:

- Updating `title`, `description`, `level` or `scope` of an `explicit` standard flags it as divergent unless `source_updated` is true.
- Expired exceptions stop applying and are reported in `alerts` until renewed (`add_exception` again with a new date) or removed.
- Standards are never deleted; use `reject` or `deprecate`.
