# Contributing to Wiki Creator

Thanks for helping grow Wiki Creator. This project turns EPUB novels into wiki
pages, and the two contributions that make it reach new communities are:

- **[Adding a language](docs/adding-a-language.md)** — a new `cue_words/<lang>.json`
  lang pack so the deterministic pipeline runs on books in your language.
- **[Adding or adapting a page template](docs/adding-a-template.md)** — new
  infobox slots, sections, tiers or localized labels in `wiki_creator/templates/`.

Both guides are self-contained; read the one that matches your contribution.
Everything below is the shared baseline: how to set up, test, and open a PR.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Report
unacceptable behavior to the maintainer at ariane@arianeguay.ca.

## Dev setup

Requires **Python 3.11+**.

```bash
git clone https://github.com/studio-foundation/wiki-creator.git
cd wiki-creator
pip install -e ".[dev]"
```

The `[dev]` extra carries `en_core_web_sm`, the model the test suite runs on, so
a fresh clone reproduces the documented test state with no extra download. You do
**not** need the `[models]`, `[gliner]` or `[coref]` extras to work on docs,
lang packs, templates, or pure-logic changes — those extras (~1 GB, plus torch)
are for running the pipeline on real books, and the tests that need them skip
cleanly when they are absent (`tests/_markers.py`).

## Verifying a change

Almost every change is proven without running the full pipeline (a full run costs
an hour and hundreds of LLM calls). Pick the smallest slice that produces evidence:

```bash
pytest -q            # the test suite — LLM-free, the whole proof for pure logic
mypy wiki_creator/   # type-check (CI runs this and fails on an error)
make golden          # deterministic resolution stages vs committed goldens (~2s)
make smoke           # end-to-end smoke test on the committed fixture novella
```

`make golden` and `make smoke` are **LLM-free by construction** — they never
call a model or need an API key. If you intentionally change a deterministic
stage's behavior, regenerate the goldens with `make golden-update` and review the
diff **in the same PR**.

CI (`.github/workflows/ci.yml`) runs `mypy wiki_creator/`, `pytest -q`, and the
`research/*-eval` pure-logic suites on Python 3.11. Green CI is required to merge.

## Conventions

- **Simplicity first, surgical changes.** Minimum code that solves the problem;
  touch only what the task requires. Every changed line should trace to the change
  you set out to make.
- **No hardcoded vocabulary in Python.** Detection words live in
  `cue_words/<lang>.json` (language-wide) or the book YAML; output strings live in
  `wiki_creator/templates/base.yaml`, keyed by language. See
  [adding a language](docs/adding-a-language.md) and
  [adding a template](docs/adding-a-template.md).
- **English is the only language in code.** Comments, identifiers, commit
  messages, PR descriptions, and docs are English. User-facing strings that need
  translation are data (YAML), never string literals in `.py`.
- **Comments explain _why_, not _what_.** Default to none; write one only when the
  code cannot say the reason itself (a hidden constraint, a workaround for a
  specific bug).

## Commits

- **[Conventional Commits](https://www.conventionalcommits.org/):** one logical
  change per commit, `type: summary` (`feat:`, `fix:`, `docs:`, `refactor:`,
  `test:`, `research(scope):`). Reference the issue key in the subject when there
  is one — `fix: gate Relationships section on usable relation data (STU-628)`.
- Commit small and often — don't batch unrelated fixes into one commit.

## Pull requests

1. Branch off `main` (never commit to `main` directly).
2. Keep the diff scoped to one change; make sure `pytest -q`, `mypy` and the
   relevant `make` targets pass locally.
3. Open a PR against `main` filling in the
   [PR template](.github/PULL_REQUEST_TEMPLATE.md). Reference the issue key in the
   body so it links back to the tracker.
4. CI must be green to merge. See [branch protection](docs/branch-protection.md)
   for the merge rules.

## Reporting bugs and requesting features

Open an issue using the templates under `.github/ISSUE_TEMPLATE/`. A good bug
report says what you ran, what you expected, and what happened — with the exact
command and the shortest error line that shows the failure.
