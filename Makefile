.PHONY: run run-series run-series-wiki run-coref run-extraction run-resolution run-preparation pages-export \
        test-extraction test-clustering test-relationships classify-relationships classify-relationships-dry \
        run-events generate-synopsis generate-synopsis-dry \
        generate-event-pages generate-event-pages-dry consolidate-stance \
        check-wikilinks check-wikilinks-series \
        generate-pages generate-pages-dry generate-pages-primary generate-pages-entity \
        discover-relationships \
        smoke golden golden-update eval-relationships coverage \
        clean

#BOOK ?= library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books/02-le-jeu-de-lange.yaml
# BOOK ?= library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
SERIES ?= library/christopher_paolini/inheritance
# BOOK ?= library/brandon_sanderson/the_stormlight_archives/books/01-the_way_of_kings.yaml
BOOK ?= library/c_w_lewis/narnia/books/01-the_lion_the_witch_and_the_wardrobe.yaml
#BOOK ?= library/j_r_r_tolkien/lord_of_the_rings/books/00-the_hobbit.yaml

# Subset test runs (STU-497): cap extraction to the first N chapters so any
# feature can be exercised end-to-end in seconds. `make run BOOK=... MAX_CHAPTERS=3`.
# Exported here once so EVERY target (run, run-extraction, …) honors it —
# parse_epub reads WIKI_MAX_CHAPTERS and truncates; all downstream stages just
# consume the shrunk artifacts. Pair with the entity subset (ENTITY=..., below) to
# also slice the generation axis. Unset = full run, no behavior change.
ifdef MAX_CHAPTERS
export WIKI_MAX_CHAPTERS := $(MAX_CHAPTERS)
endif

# `pip install -e .` pins one absolute checkout on sys.path for the whole interpreter,
# and a spawned script's own dir outranks cwd — so from a git worktree every target below
# would import wiki_creator from the INSTALLED checkout, not this one. Prepend this tree.
export PYTHONPATH := $(CURDIR)$(if $(PYTHONPATH),:$(PYTHONPATH))

# Full run: Studio orchestrates the four pipelines (STU-457, wiki-full = four
# call stages). To restart from a boundary, replay the run:
#   studio replay <run-id> --restart --stage wiki-resolution
# (run ids: `studio status`). Per-unit caches make a plain re-run cheap on the
# LLM side; only deterministic compute (extraction) re-executes.
run:
	studio run wiki-full --input-file $(BOOK) --live

# Full series run: every tome in reading order (STU-487), then the series wiki
# once (STU-709). Tome order comes from wiki_creator.series (numeric prefixes,
# 04.5 between 04 and 05) — not a shell glob sort, which puts 04.5_ before 04_.
run-series:
	@python -c "from wiki_creator.series import discover_series_books; \
	print('\n'.join(str(b) for b in discover_series_books('$(SERIES)')))" | \
	while read book; do \
		echo "=== $$book ==="; \
		studio run wiki-full --input-file $$book --live || exit 1; \
	done
	@echo "=== series wiki ==="
	studio run wiki-series --input-file $(FIRST_TOME) --live

# Any tome's yaml names the series; the first is where the arc pass reads
# language and register from anyway.
FIRST_TOME = $$(python -c "from wiki_creator.series import discover_series_books; \
	print(discover_series_books('$(SERIES)')[0])")

# Series wiki alone: assemble every tome's artifacts, then export output/_series/.
run-series-wiki:
	studio run wiki-series --input-file $(FIRST_TOME) --live

# Relationship extraction with coreference on real book data.
# device auto-detects CUDA (STU-466); on GPU workers is forced to 1.
# Override device with: make run-coref COREF_DEVICE=cpu
COREF_DEVICE ?=
run-coref: test-extraction
	python scripts/relationship_extraction.py --live --book $(BOOK) --coref \
		$(if $(COREF_DEVICE),--coref-device $(COREF_DEVICE),)

# Individual pipelines (single-stage dev tools — they sequence nothing)
run-extraction:
	studio run wiki-extraction --input-file $(BOOK) --live --verbose

run-resolution:
	studio run wiki-resolution --input-file $(BOOK) --live --verbose

run-preparation:
	studio run wiki-preparation --input-file $(BOOK) --live --verbose

pages-export:
	studio run pages-export --input-file $(BOOK) --live --verbose

generate-pages:
	python scripts/generate_wiki_pages.py --book $(BOOK)

generate-pages-dry:
	python scripts/generate_wiki_pages.py --book $(BOOK) --dry-run

# Subset re-run (STU-497): regenerate only a slice, preserve every other page.
generate-pages-primary:
	python scripts/generate_wiki_pages.py --book $(BOOK) --importance principal --force

# ENTITY required, e.g. make generate-pages-entity ENTITY="Celaena Sardothien"
generate-pages-entity:
	python scripts/generate_wiki_pages.py --book $(BOOK) --entities "$(ENTITY)" --force

generate-synopsis:
	python scripts/generate_book_synopsis.py --book $(BOOK)

generate-synopsis-dry:
	python scripts/generate_book_synopsis.py --book $(BOOK) --dry-run

generate-event-pages:
	python scripts/generate_event_pages.py --book $(BOOK)

generate-event-pages-dry:
	python scripts/generate_event_pages.py --book $(BOOK) --dry-run

# Editorial-stance consolidation pass (STU-508): advisory drift report over the
# generated pages vs the declared editorial_stance.mode. Never fails the run.
consolidate-stance:
	python scripts/consolidate_editorial_stance.py --book $(BOOK)

# Wikilink integrity (STU-725): assert every [[link]] in the rendered wiki
# resolves to a page. Hard gate — exits non-zero on a dead link. Intentional red
# links go in the book YAML export.red_links list.
check-wikilinks:
	python scripts/check_wikilinks.py --book $(BOOK)

check-wikilinks-series:
	python scripts/check_wikilinks.py --book $(BOOK) --series

test-extraction:
	python scripts/test_extraction.py --book $(BOOK)

test-clustering:
	python scripts/entity_clustering.py --test

test-relationships:
	python scripts/relationship_extraction.py --test

discover-relationships:
	python scripts/discover_relationships.py --book $(BOOK)

classify-relationships:
	python scripts/classify_relationships.py --book $(BOOK)

classify-relationships-dry:
	python scripts/classify_relationships.py --book $(BOOK) --dry-run

run-events:
	python scripts/build_event_layer.py --book $(BOOK)

smoke:  ## End-to-end smoke test on the committed fixture novella (no real EPUB needed)
	python -m pytest tests/test_e2e_smoke.py -q

golden:  ## Golden regression run: chained resolution stages vs committed goldens (fast, no spaCy/LLM)
	python -m pytest tests/test_e2e_golden.py -q

golden-update:  ## Regenerate goldens after an INTENTIONAL behavior change, then review the diff
	UPDATE_GOLDENS=1 python -m pytest tests/test_e2e_golden.py -q

coverage:  ## Coverage/faithfulness report over a run's artifacts (STU-723): chapter/alias/relation ledgers + drop log. Never fails; writes <processing>/coverage_report.json
	python scripts/coverage_report.py --book $(BOOK)

eval-relationships:  ## Score the relationship classifier against the hand-labelled gold fixture (STU-499). PREDICTIONS=<file> to score offline, else --run (needs studio/LLM)
	python scripts/eval_relationship_classifier.py \
		$(if $(PREDICTIONS),--predictions $(PREDICTIONS),--run --book $(BOOK))

clean:  ## Remove generated files (keeps .gitkeep sentinels)
	@SERIES_DIR=$$(python -c "from wiki_creator.paths import book_paths_from_yaml; p = book_paths_from_yaml('$(BOOK)'); print(p.processing.parent.parent)"); \
	find $$SERIES_DIR/processing_output $$SERIES_DIR/wiki_inputs $$SERIES_DIR/output \
	     -not -name '.gitkeep' -delete 2>/dev/null || true
