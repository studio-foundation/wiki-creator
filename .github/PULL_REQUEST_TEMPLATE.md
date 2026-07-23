## What

One-line summary of the change. Reference the issue key if there is one (e.g.
`STU-123`) so it links back to the tracker.

## Why

The problem this solves, or the behavior it changes.

## How verified

- [ ] `pytest -q`
- [ ] `mypy wiki_creator/`
- [ ] `make golden` (and `make golden-update` + reviewed diff, if behavior changed)
- [ ] `make smoke`
- [ ] Validated on a book (say which, and what you checked) — for lang packs / templates

## Checklist

- [ ] One logical change, scoped diff.
- [ ] No hardcoded vocabulary or user-facing strings in Python (data lives in
      `cue_words/<lang>.json` or `templates/base.yaml`).
- [ ] Docs updated if behavior or config changed.
