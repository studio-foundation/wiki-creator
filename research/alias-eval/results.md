# Results — alias adjudication over the library (STU-543)

15 books, full text, run 2026-07-17 on `claude-haiku-4-5`. Rosters 17–174 PERSON
entities. **18 merges, 15 true, 3 false — precision 0.83.**

Reproduce: `PYTHONPATH=../.. python run_books.py && PYTHONPATH=../.. python score.py`.

## The stage did not exist on half the library

The first thing this measured was not adjudication. Of the first 8 books run, **5
produced no verdict at all** — every large-roster one. Two bugs in series, each of
which fails safe, so the stage warned, merged nothing, and every pipeline stayed
green:

* **STU-561** (Studio) — the claude-code provider passed the prompt as argv. Linux
  caps one argv entry at 131072 bytes, so `spawn` threw `E2BIG` before the process
  existed. A Dark and Hollow Star's 78-character roster built a 173 436-char prompt
  and died in 20 ms, 0 tokens.
* **STU-564** (here) — with the call through, `studio run --json` truncates its
  stdout echo at 8 KiB, and the log-recovery path read the run id *out of the
  payload it had just failed to parse*. It only ever fired for runs that had not
  truncated.

Both bite the same books — the big ones. A stage that did nothing on half the
library read as a stage with nothing to say. **The measurement's first result is
that there was nothing to measure**, and no amount of reading the prompt would have
found it.

## Precision

| verdict | n |
| -- | --: |
| true positive | 15 |
| false positive | 3 |

Four are judged by the ground-truth corpora (`score.py`), the rest by reading the
book. Both numbers are reported; nothing unjudged is counted as a pass.

What it finds, across every roster size and both languages:

| book | roster | merge |
| -- | --: | -- |
| the_way_of_kings | 174 | `Wit = Hoid`, `Kaladin = Kal` |
| 04_inheritance | 101 | `Saphira = Bjartskular`, `Roran = Stronghammer` |
| 03_brisingr | 115 | `Eragon = Firesword`, `Saphira = Bjartskular` |
| 02_eldest | 132 | `Eragon = Argetlam`, `Roran = Stronghammer` |
| 01_eragon | 49 | `Brom = Neal`, `Eragon = Evan` — the false names they travel under |
| narnia | 17 | `The Witch = White Witch` |
| a-dark-and-hollow-star | 77 | `Rachael = Rach`, `Celadon Viridian = Uncle Cel` |
| a-cruel-and-fated-light | 66 | `Thalo = Viridian-Verdell` |

`Wit = Hoid` is worth naming. STU-538 deleted the pattern templates and recorded
that this exact pair is the shape they could never reach — *"Wit will suffice—or if
you must, you may call me Hoid"* — because it needs dialogue attribution, not a
regex. It is found here, on the largest roster in the library, from the sentence
STU-538 quoted.

**Roster size is not the failure axis the ticket expected.** 174 entities works;
the three false positives come from rosters of 49, 90 and 101.

## The three false positives are one shape

| merge | book | why it is false |
| -- | -- | -- |
| `Eragon = Uluthrek` | 04_inheritance | Uluthrek is **Angela**. *"Farewell, Firesword. Farewell, Uluthrek."* — two people, addressed in sequence. |
| `Glaedr = Ebrithil` | 04_inheritance | *Ebrithil* is "master" — Arya says it to Oromis, Saphira to Glaedr. A title several characters hold. |
| `Nausicaä Kraken = Fury` | a-grim-and-sunken-vow | There are three Furies: Alecto (Nausicaä), Tisiphone, Megaera. A class, not a person. |

Every one cites a quote that is verbatim in the snippets we showed — the STU-539
grounding check passed all three. Look at what the quotes actually say:

* `Eragon = Uluthrek` cites *"And why did Garzhvog call **you** Uluthrek?"* — Eragon
  asking **Angela** about her name. The sentence proves the name belongs to the
  person being spoken *to*. It is Solembum (STU-538) with the arrow reversed: there,
  a speaker named himself and was merged with his listener.
* `Glaedr = Ebrithil` cites *"she said to Glaedr, Tell us a story, Ebrithil"* —
  which is true, and true of Oromis in the next chapter.
* `Nausicaä = Fury` cites *"this mortal horror that had filled Nausicaä's every day
  as a Fury"* — which says she **is one of** them, the very sentence that proves
  she is not the only one.

Two of the three merge a character into a **class held by several** (Fury, Ebrithil);
one reads a second-person address as first-person. An earlier run produced a fourth
of the same family — `LUCY = Daughter of Eve`, quote *"Welcome, Susan and Lucy,
Daughters of Eve"*, a sentence that names **two** bearers of the epithet. The Narnia
gold forbids it by name (`identity_confusion_forbidden: ["alias: Daughter of Eve"]`).

This is STU-544's thesis, measured: **presence was all the quote check ever
measured**, and the class of merges it lets through is not random. STU-541 named the
same distinction from the other end — an honorific is not a role; Mr and Mrs Beaver
differ only by the title. A title that designates **one** person (`Captain of the
Guard`, `Argetlam`, `Bjartskular`) merges correctly and is most of what this stage
buys. A title shared by **many** (`Fury`, `Ebrithil`, `Daughter of Eve`) has no
referent to merge into.

## Recall

Six pairs the gold names and no merge joined, all in `inheritance`, all the same
entity: `Eragon` / `Shadeslayer` / `Argetlam` across four tomes. `Argetlam` merges in
02_eldest and not in 03_brisingr — the snippets differ per tome, and a tome whose
snippets never state the binding does not get it. Under-merging is the posture
STU-538 chose; this is what it costs.

## What is not measured

* **Run-to-run stability.** Two full passes of Throne of Glass produced 4 merges and
  then 0 — not model variance: with STU-564 fixed, `section-filter`'s verdict is
  recovered instead of discarded, the extraction differs, and `alias-resolution`
  already folds `Celaena` / `Lillian Gordaina` / `Elentiya` upstream. Nothing is left
  for adjudication to find, which is the correct 0. It does mean **STU-539's premise —
  "no signal even proposes that pair today" — is false on a correctly filtered
  extraction**, and deserves its own look.
* **A book's whole roster.** The gold covers 0–20 entities per book; a merge between
  two entities it does not name is judged by a human, and a merge nobody proposed is
  invisible to both.

## Running it

Every `invented_names` book loads GLiNER from HuggingFace, so an expired HF token
fails all 8 of them at `entity-extraction` (`401 ... OAuth token signature
verification failed`) — loudly, which is correct (STU-521: a backend must not
silently fall back). The models are cached; `HF_HUB_OFFLINE=1 python run_books.py`
runs without the network.
