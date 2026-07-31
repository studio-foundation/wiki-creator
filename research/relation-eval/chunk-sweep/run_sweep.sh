#!/usr/bin/env bash
# STU-611: sweep --chunk-chars on Narnia, snapshot each size's discovered pairs.
#
# Written for the post-STU-589/605 stage shape: the fan-out and its per-item
# resume live in the ENGINE (map stage, .studio/runs/map-cache), keyed on each
# item's resolved input — chunk text + subset roster + prompt fingerprint. Two
# sizes can never share a cache entry (different text => different key), so no
# cross-size isolation machinery is needed; a re-run of the same size resumes
# for free. The old script-side votes cache this file used to seed is retired.
#
# A failed chunk is never cached (counts as a lost vote, understating that
# size's pair set), so each size retries until the stage reports "0 failed".
#
# Runs in the main checkout: library/ and the editable install live there; the
# task worktree carries only this harness. Snapshots land beside this script.
#
# LIVE LLM RUN — one call per chunk, cold: 62 (4000) + 45 (6000) + 26 (12000)
# = 133 calls. Launch it yourself, never from an agent session.
set -uo pipefail
MAIN=/home/arianeguay/dev/src/wiki-creator-by-studio
OUT="$(cd "$(dirname "$0")" && pwd)"
BOOK=library/c_w_lewis/narnia/books/01-the_lion_the_witch_and_the_wardrobe.yaml
DISC=library/c_w_lewis/narnia/processing_output/01-the_lion_the_witch_and_the_wardrobe/relationships_discovered.json
LOG="$OUT/sweep.log"
cd "$MAIN"
export PYTHONPATH="$MAIN"

{
  echo "===== sweep $(date -Is) ====="
  echo "provider=${STUDIO_BULK_PROVIDER:-claude-code} model=${STUDIO_BULK_MODEL:-claude-haiku-4-5}"
} | tee -a "$LOG"

for size in 4000 6000 12000; do
  echo "===== chunk_chars=$size =====" | tee -a "$LOG"
  for pass in 1 2 3 4 5; do
    out=$(python scripts/discover_relationships.py --book "$BOOK" --chunk-chars "$size" 2>&1)
    printf '%s\n' "$out" | tee -a "$LOG"
    failed=$(printf '%s\n' "$out" | grep -oE '[0-9]+ failed' | head -1 | grep -oE '^[0-9]+')
    echo "[driver] size=$size pass=$pass failed=${failed:-unknown}" | tee -a "$LOG"
    cp "$DISC" "$OUT/discovered_$size.json"
    [ "${failed:-1}" = "0" ] && break
  done
done

# leave the live artifact at the shipped default size until STU-611 decides
cp "$OUT/discovered_6000.json" "$DISC"
echo "===== sweep complete; live artifact = 6000 snapshot =====" | tee -a "$LOG"
