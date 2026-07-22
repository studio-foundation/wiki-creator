#!/usr/bin/env bash
# STU-616 driver: measure spaCy vs GLiNER (t0.5, t0.3) on one book via the LLM
# oracle, saving the per-book oracle roster. Run from repo root.
set -euo pipefail

BOOK="$1"
SLUG="$(basename "$BOOK" .yaml)"

if [ -f "research/ner-eval/stu616/oracle_${SLUG}.json" ]; then
  echo "== skip $SLUG (oracle already saved) =="
  exit 0
fi

export PYTHONPATH="$(pwd)"
export WIKI_NER_DEVICE="${WIKI_NER_DEVICE:-cpu}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

PROC="$(python - "$BOOK" <<'PY'
import sys, yaml
from wiki_creator.paths import book_paths_from_yaml
print(book_paths_from_yaml(sys.argv[1]).processing)
PY
)"

if [ ! -f "$PROC/epub_data.json" ]; then
  echo "== parse $SLUG =="
  python -c "import json,pathlib,sys; y=pathlib.Path(sys.argv[1]).read_text(); print(json.dumps({'additional_context':y,'previous_outputs':{},'all_stage_outputs':{}}))" "$BOOK" \
    | python scripts/parse_epub.py > /dev/null
fi

rm -f research/ner-eval/arms/entities_*.json research/ner-eval/arms/oracle.json
echo "== arms $SLUG =="
python research/ner-eval/run_arms.py --book "$BOOK" --arm spacy
python research/ner-eval/run_arms.py --book "$BOOK" --arm gliner_t0.5 --threshold 0.5
python research/ner-eval/run_arms.py --book "$BOOK" --arm gliner_t0.3 --threshold 0.3

echo "== oracle $SLUG =="
python research/ner-eval/oracle_types.py --book "$BOOK" --min-mentions 3
mkdir -p research/ner-eval/stu616
cp research/ner-eval/arms/oracle.json "research/ner-eval/stu616/oracle_${SLUG}.json"
