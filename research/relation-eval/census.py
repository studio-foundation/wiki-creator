import json, glob, os, sys
sys.path.insert(0, os.getcwd())
from wiki_creator.relationship_discovery import chunk_chapters
from wiki_creator.chapters import is_frontmatter_chapter

def narr_chapters(epub):
    out=[]
    for c in epub.get("chapters") or []:
        if is_frontmatter_chapter(c): continue
        out.append({"id":c.get("id"),"title":c.get("title") or c.get("id") or "","text":c.get("content") or ""})
    return out

books=[]
for epub_path in sorted(glob.glob("library/*/*/processing_output/*/epub_data.json")):
    if "bak" in epub_path: continue
    proc=os.path.dirname(epub_path)
    slug=os.path.basename(proc)
    epub=json.load(open(epub_path))
    ch=narr_chapters(epub)
    chars=sum(len(c["text"]) for c in ch)
    chunks=chunk_chapters(ch, 6000)
    n=len(chunks)
    # cached?
    vpath=os.path.join(proc,"relationships_discovered_votes.json")
    cached=None; empty=None
    if os.path.exists(vpath):
        v=json.load(open(vpath))["votes"]
        cached=len(v); empty=sum(1 for x in v.values() if not x)
    print(f"{slug:40} ch={len(ch):3} chars={chars:8} chunks@6k={n:4} cachedchunks={cached} empty={empty}")
    books.append((slug,len(ch),chars,n))
tot=sum(b[3] for b in books)
print(f"\n6 books with live epub_data: total chunks@6k = {tot} (cold discovery calls)")
