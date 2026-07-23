---
name: Bug report
about: Something the pipeline does wrong or a crash
title: ""
labels: bug
assignees: ""
---

## What happened

A clear description of the bug.

## What you ran

The exact command (`wiki book run <alias>`, `make golden`, `pytest -q`, …) and,
if relevant, the book YAML or lang pack involved.

## Expected

What you expected to happen.

## Actual

What happened instead. Paste the **shortest error line** that shows the failure
(not the full log). If a page or artifact is wrong, name the file and quote the
wrong part.

## Environment

- OS:
- Python version:
- Install (`pip install -e ".[dev]"` / `.[models]` / `.[gliner]` / `.[coref]`):
- Book language / spaCy model (if relevant):
