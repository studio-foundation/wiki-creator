# STU-565 — the death circumstance on Eragon's verified verdicts

**The number: false circumstance rate 0/4. Zero rendered `agent`/`place` on
Eragon's four verified `deceased` verdicts is untrue of the novel.** STU-488
killed the derived-chapter slot at 3/4 wrong; its replacement is 0/4 wrong. The
untested direction costs an absent row, not a false one — which is the asymmetry
STU-552 shipped on, now with a measurement under it.

Reproduce: `cd research/death-circumstance-eval && PYTHONPATH=../.. python measure.py`

## What renders (best case for the model — it proposes the true killer/place)

Scenario A is the cached spaCy extraction, the one STU-488 and STU-565 measure.

```
verdict   in-book    agent        place       rendered row
Brom      yes        —            —           —
Morzan    backstory  —            —           —
Marian    backstory  —            —           —
Tornac    backstory  —            Urû'baen    Mort à Urû'baen
Vrael     backstory  —            —           —

circumstances rendered : 1/5
false circumstance rate: 0/1 fields = 0%
agent/place recall     : 1/3 stated fields surfaced
```

Brom, Morzan and Marian are the three verdicts the ticket names by hand; the
fourth is one backstory death from the same roster (STU-488 lists `Tornac`,
`Morzan`, `Marian`, `Vrael`, `Haeg`), and its exact identity lives in that run's
Studio journal, which is not in this repo — so both live candidates are measured.
Whichever is the true fourth, the four-verdict set carries **no false fact**.

## Verdict by verdict

### Brom — the ticket's "interesting positive" is a negative

The ticket expects `Tué par Durza`, and asks whether the whole-token quote gate
drops one field or keeps both. **Neither: Brom renders nothing, and the premise
is a synthetic example mistaken for the novel.**

* In the novel Brom is killed by **the Ra'zac**, not Durza, and dies of the wound
  in an unnamed cave — nowhere near Farthen Dûr. (`books/ground-truth/eragon.json`:
  *"Brom est tué par les Ra'zac"*.) "Killed by Durza at Farthen Dûr" is the
  STU-552 design doc's **synthetic illustration** of three passing gates; STU-565's
  prose inherited it as if it were the plot.
* On the cached extraction the real killer, `Ra'zac`, is typed **ORG**
  (`01_eragon.yaml`: *"Garrow, Durza, Ra'zac … it types them ORG"*). `agent` is
  gated against the PERSON roster, so it drops on type. Brom's death quote —
  `"Brom's dead," said Eragon abruptly. "The Ra'zac killed him."` (verbatim from
  STU-488's journal) — names no place. Both fields absent → **no row**.

So the "interesting positive" never occurs. The one field the novel actually
states (a killer) is dropped — a **recall miss**, by design, not a false fact.

### Morzan, Marian — dead before the book, and the gates render nothing

Exactly as the ticket wants. Neither has a death scene in this tome. Morzan is
saga-killed by Brom, but tome 1 never states it; feeding the gate the model's
memory of that (`agent: "Brom"`) is dropped by gate 3 — Brom's name is not in
Morzan's backstory quote. Marian died of the sickness: no agent exists to render.
**No `agent` or `place` on either — no false fact, which is the exact defect the
gates exist to stop.**

### The fourth verdict — a true backstory circumstance can still surface

The gates are conservative, not blind:

* **Tornac** was cut down fleeing **Urû'baen** — a roster PLACE (forced by
  `entity_overrides`) that appears in the death sentence. His killer ("the king's
  soldiers") is no roster person, so `agent` stays empty, but `place` grounds:
  **`Mort à Urû'baen`** — true. A backstory death rendering a *correct* place.
* **Vrael** was struck down by Galbatorix. On the cached roster `Galbatorix` is
  ORG (same spaCy blind spot) → dropped → nothing.

Either way the rendered field is true. The fourth verdict adds no false fact.

## The false rate is the gate's doing, not the harness's

Best-case proposals make "0 false" trivial, so the adversarial arm feeds the gate
**false** circumstances against Brom's real death quote:

```
case                                       renders
ticket's belief: Durza / Farthen Dûr       — (dropped)
hallucinated killer on the real quote      — (dropped)
real killer, wrong type (Ra'zac=ORG)       — (dropped)
synthetic sentence (design-doc example)    Mort à Farthen Dûr
```

The ticket's own false belief drops entirely: `Durza` fails the type gate and
`Farthen Dûr` fails the quote gate — neither is in `"The Ra'zac killed him."` The
last line is the control: the synthetic sentence, in isolation, **does** render
(`Mort à Farthen Dûr`, place grounded, ORG agent dropped) — proof the gate is
refusing false facts, not refusing everything. The novel simply never contains
that sentence, so it never renders on Brom.

## Recall — non-zero, cheap, as predicted

STU-565: recall misses are "expected to be non-zero by design … worth knowing the
size, not worth optimizing to zero." On the cached roster, **1 of 3** stated
killer/place fields survives:

| stated in a death sentence | surfaced? | why |
|---|---|---|
| Brom — the Ra'zac (killer) | no | Ra'zac is ORG, `agent` is PERSON-scoped |
| Vrael — Galbatorix (killer) | no | Galbatorix is ORG on the cached extraction |
| Tornac — Urû'baen (place) | yes | forced to PLACE, and in the quote |

Both misses are the **type-scoped roster** dropping a killer spaCy typed ORG, not
the quote gate. A prompt-typed re-extraction (Scenario B) recovers them —
`Tué par Galbatorix` renders, still true — lifting recall to 2/3 **without
introducing a single false fact**. The finding does not rest on the ORG typing;
the ORG typing only makes the feature *more* conservative on this tome.

## Caveats

* **No live LLM run.** The gate is deterministic and the model only proposes, so
  the measurement drives the gate directly with the novel's real death sentences
  and the model's best-case proposal. It does not re-derive which snippet the
  classifier would cite for the backstory deaths, nor confirm the fourth verdict's
  identity — both live in the STU-488 run journal, absent from this repo. The
  headline (0 false) is robust to those unknowns: no backstory death has an
  in-tome sentence co-naming a PERSON-typed roster killer and the subject.
* **Roster typing is the pivot.** The result is reported on the cached extraction
  (Scenario A) because that is what STU-488/565 measured; Scenario B shows a
  re-extraction changes recall, never the 0 false rate.
* Not a CI metric — a one-time count, the control that stops shipping a false
  killer the way STU-538 shipped 340 fires for 0 true positives with nobody
  counting.

## Verdict

The death circumstance clears STU-488's bar on Eragon: **0/4 false**, against the
chapter slot's 3/4 wrong. It is not blocking, and now there is a number that says
so. The cost of the untested direction is an absent row (Brom, whose real killer
is an ORG the roster cannot name) — never a wrong one.
