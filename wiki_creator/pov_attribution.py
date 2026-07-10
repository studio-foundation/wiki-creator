"""Deterministic POV-character attribution for a single chapter.

Given raw chapter text and its POV *type* (from parse_epub's detect_pov), name
the most likely focal character by capitalized-name frequency, weighted by
proximity to third-person thought markers. Returns a high/medium/low certainty
label so callers can gate on it (high → trust; otherwise fall back to an LLM or
abstain). When thought markers are configured, a candidate must sit next to one
to earn "high" — the focal character is the one being thought with, which guards
against a frequently-named place or side character winning on raw frequency.

All vocabulary — thought markers and name-exclusion words — is passed in from
cue_words/<lang>.json. Nothing is hardcoded here (CLAUDE.md invariant); an empty
vocab simply weakens the signal, it never crashes.

Known limitation: sentence-initial capitalization inflates common words. The
certainty gate is the safeguard — ambiguous chapters resolve to medium/low and
are handled by the LLM fallback or abstention, not a confident wrong guess.
"""
from __future__ import annotations

import re

# POV types that have a single focal character worth attributing.
_SUBJECTIVE_POV = {"first_person", "third_limited"}

# Certainty-gate thresholds (design STU-426). Kept together so the policy is
# tunable in one place.
_MIN_ABS_HIGH = 3      # top candidate must occur >= this many times for "high"
_SHARE_HIGH = 0.5      # ... and hold >= this share of total weighted mass
_MARGIN_HIGH = 0.2     # ... and lead the runner-up by this share of the mass
_SHARE_MEDIUM = 0.35   # medium floor
_PROXIMITY_WINDOW = 8  # tokens; an occurrence within this of a marker gets a bonus
_PROXIMITY_BONUS = 1.0 # extra weight per marker-adjacent occurrence

_STRIP = ".,;:!?\"'()[]«»…—–"
_CAP_RE = re.compile(r"^[A-ZÀ-Ý][\wÀ-ÿ'’\-]+$")


def _clean(token: str) -> str:
    return token.strip(_STRIP)


def attribute_pov_character(
    content: str,
    pov: str,
    thought_markers: tuple[str, ...] = (),
    exclusion_words: tuple[str, ...] = (),
) -> dict:
    none_result = {"pov_character": None, "pov_character_confidence": "low"}
    if pov not in _SUBJECTIVE_POV or not content:
        return none_result

    exclusion = {w.lower() for w in exclusion_words}
    markers = {m.lower() for m in thought_markers}

    tokens = content.split()
    marker_idx = [i for i, t in enumerate(tokens) if _clean(t).lower() in markers]

    counts: dict[str, int] = {}
    weights: dict[str, float] = {}
    marker_hits: dict[str, int] = {}
    i, n = 0, len(tokens)
    while i < n:
        cleaned = _clean(tokens[i])
        if not _CAP_RE.match(cleaned):
            i += 1
            continue
        start = i
        span_tokens: list[str] = []
        while i < n:
            c = _clean(tokens[i])
            if not _CAP_RE.match(c):
                break
            span_tokens.append(c)
            i += 1
        # Drop a span that is a single excluded (title-cased stopword/role) token.
        if len(span_tokens) == 1 and span_tokens[0].lower() in exclusion:
            continue
        span = " ".join(span_tokens)
        counts[span] = counts.get(span, 0) + 1
        weight = 1.0
        if any(abs(start - mi) <= _PROXIMITY_WINDOW for mi in marker_idx):
            weight += _PROXIMITY_BONUS
            marker_hits[span] = marker_hits.get(span, 0) + 1
        weights[span] = weights.get(span, 0.0) + weight

    if not weights:
        return none_result

    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    top_span, top_w = ranked[0]
    second_w = ranked[1][1] if len(ranked) > 1 else 0.0
    total_w = sum(weights.values())
    top_share = top_w / total_w if total_w else 0.0
    margin = (top_w - second_w) / total_w if total_w else 0.0

    # A dominant name only earns "high" if it is the one the narration is
    # actually thinking with (marker-adjacent). This is the defining signal of a
    # limited POV and guards against a frequently-named place or side character
    # winning on raw frequency while the true focal character hides behind
    # pronouns. When no thought markers are configured, fall back to frequency.
    top_is_focal = (not markers) or marker_hits.get(top_span, 0) > 0
    if (
        counts[top_span] >= _MIN_ABS_HIGH
        and top_share >= _SHARE_HIGH
        and margin >= _MARGIN_HIGH
        and top_is_focal
    ):
        confidence = "high"
    elif top_share >= _SHARE_MEDIUM:
        confidence = "medium"
    else:
        confidence = "low"
    return {"pov_character": top_span, "pov_character_confidence": confidence}
