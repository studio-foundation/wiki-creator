import json

from wiki_creator import audit
from wiki_creator.ground_truth import load_entries


def _gt(tmp_path, payload):
    (tmp_path / "gt.json").write_text(json.dumps(payload))
    return load_entries(tmp_path)


ALICE_GT = {
    "alice": {
        "canonical_aliases_book1": ["Alice"],
        "known_facts_book1": ["fell down the rabbit-hole"],
        "known_relations_book1": {"Dinah": "Her cat"},
        "forbidden_book1": {
            "sequel_only": ["Looking-Glass world"],
            "not_in_this_book": ["Bill is an enemy of Alice"],
        },
        "hallucination_signals": ["ruby slippers"],
        "identity_confusion_forbidden": ["alias: Mabel"],
    },
    "bill": {
        "canonical_aliases_book1": ["Bill"],
        "known_facts_book1": ["went down the chimney"],
    },
    "dinah": {
        "canonical_aliases_book1": ["Dinah"],
        "known_facts_book1": ["is Alice's cat"],
        "forbidden_book1": {"sequel_only": ["Dinah's kittens"]},
    },
}


def _page(title, content="", infobox=None, **extra):
    return {"title": title, "content": content,
            "infobox_fields": infobox or {}, **extra}


def test_signal_fires_only_on_owner_page(tmp_path):
    entries, by_entity = _gt(tmp_path, ALICE_GT)
    pages = [
        _page("Alice", "She wore ruby slippers."),
        _page("Bill", "He mentioned ruby slippers."),
    ]
    results = audit.validate_ground_truth(pages, entries, by_entity)
    assert any("HALLUC_SIGNAL" in v for v in results[0].violations)
    assert not results[1].violations


def test_identity_confusion_and_infobox_alias_cross(tmp_path):
    entries, by_entity = _gt(tmp_path, ALICE_GT)
    pages = [_page("Alice", "Some text alias: Mabel here.", {"alias": "Dinah"})]
    (r,) = audit.validate_ground_truth(pages, entries, by_entity)
    assert any(v.startswith("IDENTITY_CONFUSION") for v in r.violations)
    assert any("INFOBOX_ALIAS_CROSS [Alice→Dinah]" in v for v in r.violations)


def test_forbidden_word_boundary_not_substring(tmp_path):
    entries, by_entity = _gt(tmp_path, {
        "bree": {
            "canonical_aliases_book1": ["Bree"],
            "known_facts_book1": ["a horse"],
            "forbidden_book1": {"other": ["Bree"]},
        }
    })
    pages = [_page("Bree", "A gentle breeze blew.")]
    (r,) = audit.validate_ground_truth(pages, entries, by_entity)
    assert not r.violations


def test_forbidden_attribution_suppression(tmp_path):
    entries, by_entity = _gt(tmp_path, ALICE_GT)
    # Owner page, term attributed to another GT entity just before -> suppressed.
    suppressed = _page("Alice", "Her cat Dinah dreamed of the Looking-Glass world.")
    # Owner page, unattributed -> flagged.
    flagged = _page("Alice", "She remembered the Looking-Glass world.")
    r_sup, r_flag = audit.validate_ground_truth([suppressed, flagged], entries, by_entity)
    assert not any("Looking-Glass" in v for v in r_sup.violations)
    assert any("FORBIDDEN [Alice/sequel_only]" in v for v in r_flag.violations)


def test_foreign_forbidden_needs_owner_named_before(tmp_path):
    entries, by_entity = _gt(tmp_path, ALICE_GT)
    # Dinah's forbidden term on Bill's page, owner named before -> contamination.
    contaminated = _page("Bill", "He spoke of Dinah and Dinah's kittens.")
    # Same term, owner not adjacent -> legitimate mention, not flagged.
    legitimate = _page("Bill", "A story about Dinah's kittens.")
    r_cont, r_leg = audit.validate_ground_truth([contaminated, legitimate], entries, by_entity)
    assert any("FORBIDDEN [Dinah/sequel_only]" in v for v in r_cont.violations)
    assert not r_leg.violations


def test_structured_rel_slot_polarity(tmp_path):
    entries, by_entity = _gt(tmp_path, ALICE_GT)
    # enemies slot naming Bill: corpus says "Bill is an enemy of Alice" -> hard hit.
    enemies = _page("Alice", "", {"enemies": "[[Bill]]"})
    # friends slot naming Dinah: known relation -> no violation, no advisory.
    friends = _page("Alice", "", {"friends_allies": "[[Dinah]]"})
    # friends slot naming Bill: no forbidden with friend polarity -> advisory only.
    advisory = _page("Alice", "", {"friends_allies": "[[Bill]]"})
    r_en, r_fr, r_adv = audit.validate_ground_truth(
        [enemies, friends, advisory], entries, by_entity
    )
    assert any("STRUCTURED_REL [Alice/enemies]" in v for v in r_en.violations)
    assert not r_fr.violations and not r_fr.advisories
    assert not r_adv.violations
    assert any("REL_ABSENT" in a for a in r_adv.advisories)


def test_page_metrics_flags_and_known_issues():
    pages = [
        _page("A", "text with id.xhtml inside", {"- role": "x"}),
        _page("B", "Kiera Cass appeared. She was a queen. is the story"),
        _page("C", "", {}, _failed=True),
    ]
    ki = {"hallucination_keywords": {"Kiera Cass": "halluc_KieraCass"},
          "duplicate_titles": ["B", "Z"]}
    out = audit.page_metrics(pages, ki)
    assert "IDs_EPUB" in out["rows"][0]["issues"]
    assert "clés_préfixées" in out["rows"][0]["issues"]
    assert "halluc_KieraCass" in out["rows"][1]["issues"]
    assert "_failed" in out["rows"][2]["issues"]
    assert out["summary"]["duplicates_present"] == ["B"]
    assert out["summary"]["epub_ids"] == 1


def test_pages_from_wiki_dir(tmp_path):
    char_dir = tmp_path / "characters"
    char_dir.mkdir()
    (char_dir / "White_Rabbit.wiki").write_text(
        "{{Infobox character\n|nom=White Rabbit\n|enemies=[[Queen]]\n}}\n\n"
        "== Biography ==\nAlways late.\n"
    )
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "Infobox_character.wiki").write_text("{{Infobox character\n|nom=x\n}}")
    pages = audit.pages_from_wiki_dir(tmp_path)
    assert len(pages) == 1
    (p,) = pages
    assert p["title"] == "White Rabbit"
    assert p["infobox_fields"] == {"nom": "White Rabbit", "enemies": "[[Queen]]"}
    assert "Always late." in p["content"]
    assert "{{Infobox" not in p["content"]


def test_trace_terms_first_seen(tmp_path):
    early = tmp_path / "entities_classified.json"
    late = tmp_path / "wiki_pages.json"
    early.write_text(json.dumps({"entities": ["Aelin appears"]}))
    late.write_text(json.dumps({"pages": ["Aelin again", "Terrasen"]}))
    stages = [("entities_classified", early), ("missing", tmp_path / "nope.json"),
              ("wiki_pages", late)]
    out = audit.trace_terms(["Aelin", "Terrasen", "Ghost"], stages)
    assert out["Aelin"]["first_seen"] == "entities_classified"
    assert out["Terrasen"]["first_seen"] == "wiki_pages"
    assert out["Ghost"]["first_seen"] is None
    assert dict(out["Aelin"]["stages"])["missing"] is None


def test_coverage(tmp_path):
    proc = tmp_path / "processing"
    inputs = tmp_path / "inputs"
    proc.mkdir(), inputs.mkdir()
    (inputs / "batch_001.json").write_text(json.dumps(
        {"entities": [{"canonical_name": "Alice"}, {"canonical_name": "Bill"}]}
    ))
    (proc / "wiki_pages.json").write_text(json.dumps({"pages": [
        {"title": "Alice"}, {"title": "Bill", "_failed": True}
    ]}))
    (proc / "entities_classified.json").write_text(json.dumps({"entities": [
        {"canonical_name": "Alice"}, {"canonical_name": "Bill"},
        {"canonical_name": "Gryphon"},
    ]}))
    cov = audit.coverage(proc, inputs)
    assert cov["missing_from_pages"] == []
    assert cov["failed_pages"] == ["Bill"]
    assert cov["filtered_before_batch"] == ["Gryphon"]


def test_batch_stats_weak_and_gt_mismatch(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "batch_001.json").write_text(json.dumps({"entities": [
        {"canonical_name": "Alice", "relationships": [
            {"entity_a": "Alice", "entity_b": "Queen",
             "relationship_type": "ally", "evidence": "e",
             "evolution": "grows", "key_moments": ["m"]},
        ]},
        {"canonical_name": "Bill", "relationships": []},
    ]}))
    by_entity = {"Alice": {"known_relations_book1": {"Queen": "her enemy, the rival"}}}
    stats = audit.batch_stats(inputs, by_entity)
    names = {r["name"]: r for r in stats["entities"]}
    assert names["Bill"]["issues"] == ["0 relations"]
    assert any("but GT says antagonist" in m for m in names["Alice"]["mismatches"])
    assert stats["global"]["relations"] == 1
    assert stats["global"]["type_distribution"] == {"ally": 1}


def test_provider_mix_env_interpolation(tmp_path):
    studio = tmp_path / ".studio"
    agents = studio / "agents"
    agents.mkdir(parents=True)
    (studio / "config.yaml").write_text(
        "providers:\n  x: 1\ndefaults:\n"
        "  provider: ${STUDIO_BULK_PROVIDER:-claude-code}\n"
        "  model: ${STUDIO_BULK_MODEL:-claude-haiku-4-5}\n"
    )
    (agents / "section-filter.agent.yaml").write_text(
        "provider: ${STUDIO_SMART_PROVIDER:-claude-code}\n"
        "model: ${STUDIO_SMART_MODEL:-claude-haiku-4-5}\n"
    )
    mix = audit.provider_mix(tmp_path, env={"STUDIO_SMART_MODEL": "claude-sonnet-5"})
    assert mix["defaults"] == {"provider": "claude-code", "model": "claude-haiku-4-5"}
    assert mix["section-filter"]["model"] == "claude-sonnet-5"
