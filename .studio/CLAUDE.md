# CLAUDE.md — .studio/

Studio config & providers. Moved verbatim from the root CLAUDE.md Gotchas section so it loads only when working under `.studio/`.

## Gotchas

- `.studio/config.yaml` and `.studio/runs/` must not be committed. **`defaults`
  in that file drives every LLM stage except the five whole-book verdict agents**
  (`section-filter`, `alias-adjudication`, `entity-status`, `entity-affiliation`,
  `entity-species`), which pin `provider: claude-code` / `model:
  claude-haiku-4-5` in their own agent yaml (STU-624): each is one strict-JSON
  call per book over a large roster/section list, and a small local model
  (`mistral:7b-instruct`, the current gitignored default) loses their output
  contract on big books — echoes the input, apologises, emits degenerate tokens —
  and thrashes all 3 RALPH attempts, so its safe default engages and the feature
  silently vanishes on that book. The high-volume per-item map fan-outs
  (`chapter-summaries`, `discover-relationships`, `classify-relationships`,
  `wiki-pages`) keep the cheap local default — that is where the usage win lives.
  Every accuracy figure recorded in this file was measured on `claude-haiku-4-5`,
  which is what the five verdict agents now pin. `--provider X` still overrides
  every agent (e.g. `--provider mock` for tests). Since `config.yaml` is
  gitignored, the committed `.studio/config.example.yaml` is the only
  referenceable statement of the default; keep the two in step.
  **The two tiers were meant to be `.env`-settable** (`.env.example`): the
  five verdict agents were to read `${STUDIO_SMART_PROVIDER:-claude-code}` /
  `${STUDIO_SMART_MODEL:-claude-haiku-4-5}` from their agent yaml, and
  `defaults` reads `${STUDIO_BULK_PROVIDER}` / `${STUDIO_BULK_MODEL}`, so a run
  could retarget either tier without editing a committed file. This needs
  Studio's agent-YAML env interpolation (studio#209), which has never shipped
  (still open as of Studio 0.9.0, the latest release) — so **every run of the
  five verdict agents has failed since PR #261 introduced the template**,
  every stage that uses one (`Provider not found:
  ${STUDIO_SMART_PROVIDER:-claude-code}`), invisibly, because their on-failure
  behavior is the safe-default fallback (see "A Long Run Persists" in the root
  CLAUDE.md) — the run completes, it just never got that verdict.
  PR #303 hardcoded `provider: claude-code` back into all five agent yamls as
  a stopgap. `model` is still templated (`${STUDIO_SMART_MODEL:-claude-haiku-4-5}`)
  and equally uninterpolated — untouched only because nothing has surfaced a
  concrete failure from it yet, not because it's confirmed fine; revisit once
  studio#209 ships or once model needs retargeting again. `--provider X` still
  overrides both tiers at once, the flag path — unaffected by this.
