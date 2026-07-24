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
  **The two tiers are `.env`-settable** (`.env.example`): the five verdict
  agents read `${STUDIO_SMART_PROVIDER:-claude-code}` /
  `${STUDIO_SMART_MODEL:-claude-haiku-4-5}` from their agent yaml, and
  `defaults` reads `${STUDIO_BULK_PROVIDER}` / `${STUDIO_BULK_MODEL}`, so a run
  can retarget either tier without editing a committed file — all-claude-code is
  pointing BULK at claude-code too. Unset = the pin, so an absent `.env` changes
  nothing. This needs Studio's agent-YAML env interpolation (studio#209);
  before it lands, a literal `${...}` in an agent yaml is passed through as the
  provider name and fails. `--provider X` still overrides both tiers at once,
  the flag path.
