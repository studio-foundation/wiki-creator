#!/usr/bin/env bash
# STU-616: measure all invented-world public_domain books (alice already done).
# Sequential on CPU. Each book's score table is echoed with a clear banner so the
# shared log can be read incrementally.
set -uo pipefail
export WIKI_NER_DEVICE=cpu
cd /home/arianeguay/dev/src/wc-stu616

BOOKS=(
  public_domain/h_p_lovecraft/the_call_of_cthulhu/books/01-the_call_of_cthulhu.yaml
  public_domain/l_frank_baum/oz/books/01-the_wonderful_wizard_of_oz.yaml
  public_domain/l_frank_baum/oz/books/02-the_marvelous_land_of_oz.yaml
  public_domain/l_frank_baum/oz/books/03-ozma_of_oz.yaml
  public_domain/l_frank_baum/oz/books/04-dorothy_and_the_wizard_in_oz.yaml
  public_domain/l_frank_baum/oz/books/05-the_road_to_oz.yaml
  public_domain/l_frank_baum/oz/books/06-the_emerald_city_of_oz.yaml
  public_domain/homer/the_odyssey/books/01-the_odyssey.yaml
)

for B in "${BOOKS[@]}"; do
  SLUG="$(basename "$B" .yaml)"
  echo ""
  echo "########## BEGIN $SLUG ##########"
  if bash research/ner-eval/flip_measure.sh "$B" 2>/dev/null; then
    echo "########## END $SLUG (ok) ##########"
  else
    echo "########## END $SLUG (FAILED rc=$?) ##########"
  fi
done
echo ""
echo "%%%%%%%%%% ALL DONE %%%%%%%%%%"
