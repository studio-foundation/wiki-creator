import json, os, sys, yaml
sys.path.insert(0, os.getcwd())
import tiktoken
enc=tiktoken.get_encoding("cl100k_base")
def T(s): return len(enc.encode(s if isinstance(s,str) else json.dumps(s,ensure_ascii=False)))

from wiki_creator.relationship_discovery import chunk_chapters, build_roster
from wiki_creator.chapters import is_frontmatter_chapter
from wiki_creator.page_templates import relationship_definitions

R="library/c_w_lewis/narnia/processing_output/01-the_lion_the_witch_and_the_wardrobe"
epub=json.load(open(f"{R}/epub_data.json"))
ch=[{"id":c["id"],"title":c.get("title") or c["id"],"text":c.get("content") or ""} for c in epub["chapters"] if not is_frontmatter_chapter(c)]
chunks=chunk_chapters(ch,6000)

# system prompt = agent yaml + invariants (auto-injected)
disc_sys = T(open(".studio/agents/relationship-discovery.agent.yaml").read()) + T(open(".studio/invariants.md").read())
type_defs = relationship_definitions()
roster = json.load(open(f"{R}/relationships_discovered_votes.json"))["roster"]
fixed = T(roster) + T(type_defs)   # per-call, book-constant

passage_tok = sum(T(c["text"]) for c in chunks)
n=len(chunks)
disc_input = n*disc_sys + n*fixed + passage_tok
print(f"DISCOVERY (Narnia, {n} chunks):")
print(f"  system/call={disc_sys}  roster+types/call={fixed}  passage_total={passage_tok}")
print(f"  input tokens (cold) = {disc_input:,}   per chunk avg = {disc_input//n:,}")
print(f"  cached re-run input tokens = 0")

# CLASSIFY on discovered graph: 32 PERSON-PERSON pairs, prose pass
clf_sys = T(open(".studio/agents/relationship-classifier.agent.yaml").read()) + T(open(".studio/invariants.md").read())
disc=json.load(open(f"{R}/relationships_discovered.json"))
pairs=disc["relationships"]
# per-pair payload: type vocab + evidence + sampled contexts. Approx from evidence+shared fields present.
per_pair_body = sum(T(p) for p in pairs)/len(pairs)
clf_input = len(pairs)*clf_sys + per_pair_body*len(pairs)  # lower bound (excludes role contexts we can't fully rebuild)
print(f"\nCLASSIFY (Narnia, {len(pairs)} pairs, prose pass):")
print(f"  system/call={clf_sys}  pair-body avg~{int(per_pair_body)}")
print(f"  input tokens (lower bound) = {int(clf_input):,}")
print(f"\nSystem prompt share of a discovery call: {disc_sys/(disc_input//n):.0%}")
