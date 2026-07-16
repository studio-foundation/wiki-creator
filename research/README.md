# research/

Benchmarks and one-off evaluations. Nothing here runs in the pipeline, and
nothing in `wiki_creator/` or `scripts/` may import from here.

| dir | what it decides |
|---|---|
| `ner-eval/` | which NER backend finds the entities (STU-470, STU-521) |
| `relation-eval/` | which mechanism discovers relations (STU-467) |

## Each eval runs in its own process

    cd research/<name> && PYTHONPATH=../.. python -m pytest tests/ -q

Not `pytest research/`, and not a bare `pytest` from the root — both collect two
evals into one process, and that cannot work. The dirs are hyphenated, so they
are not importable as packages; each eval reaches its own modules by putting its
own directory on `sys.path`. Two evals in one process therefore share one
top-level namespace, and `ner-eval/score.py` and `relation-eval/score.py` are both
just `score` — first import wins, the other eval's tests silently run against the
wrong module.

That is not hypothetical: it is what a bare `pytest -q` did the day the second
eval landed, and the failure reads as `AttributeError` inside the *other* eval's
file, which is a genuinely confusing place to start debugging.

`[tool.pytest.ini_options] testpaths = ["tests"]` in `pyproject.toml` keeps the
root suite to the pipeline's own tests. CI runs each eval as its own step.

## Adding an eval

- Own directory, own `README.md`, own `requirements.txt` (deps here are heavy and
  are not in the `dev` extra — CI installs none of them).
- Own `tests/`, run by its own CI step. Do not add it to `testpaths`.
- Reuse pure logic from `wiki_creator/` by importing it (`sys.path.insert` to the
  repo root) rather than restating it — a benchmark that reimplements the thing it
  measures, measures the reimplementation.
