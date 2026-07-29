"""Narrative-arc act structure (STU-666): how a character's participant events are
split into setup / rising action / resolution, per book.

STU-663 selects the ``narrative_role`` events as three position-based acts and
splits the budget by a fixed 25/50/25. The right act boundaries are a property of
the *book*, not the pipeline — a children's tale with one setup chapter and an
adult novel whose first three chapters are all exposition want different shapes.
This declares that shape in the book YAML (``generation.narrative_arc``), per the
"Config Is Read By People Who Know Books" rule, in two mutually-exclusive modes:

    generation:
      narrative_arc:
        weights: [0.20, 0.60, 0.20]     # mode A — tune the three-act proportions

    generation:
      narrative_arc:
        acts:                            # mode B — assign chapters to acts directly
          setup: [1, 3]
          rising: [4, 22]
          resolution: [23, 25]

``max_events`` (STU-713) sets how many beats the arc carries — the budget the
weights divide — and is orthogonal to the mode above (it may accompany either, or
stand alone with the default 25/50/25):

    generation:
      narrative_arc:
        max_events: 21                   # default 18

Absent → the 25/50/25 default and 18-event budget (byte-identical to STU-663). A
present-but-empty or malformed block raises rather than degrading (STU-470: a
silently ignored config is the bug).
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_ACT_WEIGHTS: tuple[float, float, float] = (0.25, 0.50, 0.25)
DEFAULT_MAX_EVENTS = 18

_ACT_KEYS = ("setup", "rising", "resolution")


@dataclass(frozen=True)
class NarrativeArc:
    """The declared act structure: either three proportion weights (mode A) or three
    explicit inclusive chapter ranges (mode B), exactly one set, plus ``max_events``
    — the number of beats the arc carries (STU-713), which the weights divide."""

    weights: tuple[float, float, float] | None = DEFAULT_ACT_WEIGHTS
    acts: tuple[tuple[int, int], tuple[int, int], tuple[int, int]] | None = None
    max_events: int = DEFAULT_MAX_EVENTS

    def partition(
        self, chapters: list[int]
    ) -> tuple[tuple[set[int], set[int], set[int]], tuple[float, float, float]]:
        """Split the sorted event-bearing chapters into (setup, middle, resolution)
        and return the per-act budget weights. Mode A partitions by position with
        the declared weights; mode B by the declared ranges, weighting each act by
        its share of the covered chapters."""
        if self.acts is not None:
            return self._partition_by_ranges(chapters)
        return self._partition_by_weights(chapters)

    def _partition_by_weights(
        self, chapters: list[int]
    ) -> tuple[tuple[set[int], set[int], set[int]], tuple[float, float, float]]:
        weights = self.weights or DEFAULT_ACT_WEIGHTS
        n = len(chapters)
        setup = set(chapters[: round(n * weights[0])])
        epilogue = set(chapters[n - round(n * weights[2]) :]) - setup
        middle = set(chapters) - setup - epilogue
        return (setup, middle, epilogue), weights

    def _partition_by_ranges(
        self, chapters: list[int]
    ) -> tuple[tuple[set[int], set[int], set[int]], tuple[float, float, float]]:
        assert self.acts is not None
        (setup_r, rising_r, res_r) = self.acts
        in_r = lambda ch, r: r[0] <= ch <= r[1]
        setup = {c for c in chapters if in_r(c, setup_r)}
        middle = {c for c in chapters if in_r(c, rising_r)}
        epilogue = {c for c in chapters if in_r(c, res_r)}
        uncovered = set(chapters) - setup - middle - epilogue
        if uncovered:
            raise ValueError(
                "generation.narrative_arc.acts do not cover chapters "
                f"{sorted(uncovered)} (declared span "
                f"{setup_r[0]}-{res_r[1]})"
            )
        sizes = (len(setup), len(middle), len(epilogue))
        total = sum(sizes) or 1
        return (setup, middle, epilogue), (sizes[0] / total, sizes[1] / total, sizes[2] / total)


def narrative_arc(book_cfg: dict) -> NarrativeArc:
    """The book's declared act structure, or the 25/50/25 default when absent."""
    cfg = (book_cfg.get("generation") or {}).get("narrative_arc")
    if cfg is None:
        return NarrativeArc()
    if not isinstance(cfg, dict):
        raise ValueError("generation.narrative_arc must be a mapping")
    max_events = (
        _parse_max_events(cfg["max_events"])
        if "max_events" in cfg
        else DEFAULT_MAX_EVENTS
    )
    has_weights, has_acts = "weights" in cfg, "acts" in cfg
    if has_weights and has_acts:
        raise ValueError(
            "generation.narrative_arc: 'weights' and 'acts' are mutually exclusive"
        )
    if has_acts:
        return NarrativeArc(weights=None, acts=_parse_acts(cfg["acts"]), max_events=max_events)
    if has_weights:
        return NarrativeArc(weights=_parse_weights(cfg["weights"]), acts=None, max_events=max_events)
    if "max_events" in cfg:
        return NarrativeArc(max_events=max_events)
    raise ValueError(
        "generation.narrative_arc must declare 'weights', 'acts' or 'max_events'"
    )


def _parse_max_events(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError("generation.narrative_arc.max_events must be an integer")
    if raw < 1:
        raise ValueError("generation.narrative_arc.max_events must be >= 1")
    return raw


def _parse_weights(raw: object) -> tuple[float, float, float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        raise ValueError("generation.narrative_arc.weights must be three values")
    try:
        w = tuple(float(x) for x in raw)
    except (TypeError, ValueError):
        raise ValueError("generation.narrative_arc.weights must be three numbers")
    if any(x < 0 for x in w):
        raise ValueError("generation.narrative_arc.weights must be non-negative")
    if abs(sum(w) - 1.0) > 1e-6:
        raise ValueError(
            f"generation.narrative_arc.weights must sum to 1.0 (got {sum(w)})"
        )
    return w  # type: ignore[return-value]


def _parse_acts(raw: object) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    if not isinstance(raw, dict):
        raise ValueError("generation.narrative_arc.acts must be a mapping")
    if set(raw) != set(_ACT_KEYS):
        raise ValueError(
            "generation.narrative_arc.acts must declare exactly setup/rising/resolution"
        )

    def rng(key: str) -> tuple[int, int]:
        v = raw[key]
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise ValueError(
                f"generation.narrative_arc.acts.{key} must be a [first, last] chapter pair"
            )
        lo, hi = int(v[0]), int(v[1])
        if lo > hi:
            raise ValueError(
                f"generation.narrative_arc.acts.{key}: first chapter {lo} > last {hi}"
            )
        return (lo, hi)

    setup, rising, resolution = rng("setup"), rng("rising"), rng("resolution")
    if rising[0] != setup[1] + 1 or resolution[0] != rising[1] + 1:
        raise ValueError(
            "generation.narrative_arc.acts must be contiguous with no gaps or overlaps"
        )
    return (setup, rising, resolution)
