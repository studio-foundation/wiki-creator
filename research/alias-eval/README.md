# alias-eval

What contextual alias adjudication (STU-539) actually decides, measured over the
whole library instead of the one book it was designed against (STU-543).

STU-539 shipped on Throne of Glass: 2 merges, 0 false positives, on a **5-chapter**
cache. That is a sample of one, and it is the book the prompt and `select_snippets`
were built for. The stage is biased against the merge and every failure path merges
nothing, so an unmeasured book risks missed recall, not a corrupted registry — this
eval buys a number, not a safety net.

## Run it

    HF_HUB_OFFLINE=1 PYTHONPATH=../.. python run_books.py    # every book, full text
    PYTHONPATH=../.. python run_books.py --only 01_eragon
    PYTHONPATH=../.. python score.py
    PYTHONPATH=../.. python -m pytest tests/ -q              # this eval's own logic

No `requirements.txt`: unlike the other evals, this one drives the pipeline instead
of replacing a piece of it, so it needs nothing beyond the repo's own install.

`HF_HUB_OFFLINE=1` because every `invented_names` book loads GLiNER from
HuggingFace, and an expired HF token fails all 8 of them at `entity-extraction`
(`401 ... OAuth token signature verification failed`) — loudly, which is correct
(STU-521: a backend must not silently fall back). The models are cached.

`run_books.py` calls the two real pipelines (`wiki-extraction`, `wiki-resolution`)
per book — nothing here reimplements a stage — and copies each
`processing_output/<slug>/alias_adjudication.json` into `verdicts/`. Series tomes
run in reading order, so each seeds from the accumulated series registry the way
production does. A book already in `verdicts/` is skipped; delete the file to re-run.

Two stages call the network, one call each per book: `section-filter` and
`alias-adjudication`. The wall-clock cost is `relationship-extraction`, which is
deterministic and offline.

## How a merge is judged

`score.py` reads the hand-written ground-truth corpora that three books ship
(`library/<author>/<series>/books/ground-truth/*.json`). Each file names one
character and every name book 1 calls it, which is exactly the question adjudication
answers:

| both names are aliases of | verdict |
| -- | -- |
| the same gold character | true positive |
| different gold characters | false positive |
| one is not in the gold | unjudged — listed for a human, never scored as a pass |

The gold covers a handful of characters per book, never a whole roster, so
`unjudged` is the normal case. Recall is reported only where the gold can see it:
two roster rows the gold says are one character, that no merge joined.

`results.md` records the verdicts and the human judgment on the unjudged ones.
