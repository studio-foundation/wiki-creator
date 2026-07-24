// Resolve and wire the parser's [[wikilinks]] into navigation (STU-650).
//
// The STU-647 parser emits `<a class="wikilink" data-target="…">`; here we map
// each target to a page route (via the index), a category route, or mark it a
// red link when no page matches — mirroring the exporter's title→filename
// mapping so resolution can't drift from what wiki_export.py wrote.

/** MediaWiki-style page key: underscores ≡ spaces, first letter case-folded up.
 * So `[[wonderland]]`, `[[Wonderland]]` and the file `Wonderland.wiki` all
 * resolve to the same page. */
function normKey(s) {
  const t = String(s).trim().replace(/_/g, ' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** Build a resolver over the page index. `resolve(target)` returns one of:
 *   { kind: 'page', slug }      — an existing page (route `#/<slug>`)
 *   { kind: 'category', name }  — a category (route `#/category/<name>`)
 *   { kind: 'missing' }         — no such page (red link)
 */
export function buildResolver(pages) {
  const byKey = new Map();
  for (const p of pages) {
    byKey.set(normKey(p.title), p.slug);
    // also the bare filename stem, so a link written as the file name resolves
    byKey.set(normKey(p.slug.split('/').pop()), p.slug);
  }
  return function resolve(rawTarget) {
    const target = String(rawTarget ?? '').trim();
    const cat = target.match(/^:?Category:(.+)$/i);
    if (cat) return { kind: 'category', name: cat[1].trim() };
    const slug = byKey.get(normKey(target));
    return slug ? { kind: 'page', slug } : { kind: 'missing' };
  };
}

/** Turn each `a.wikilink` in `root` into a real link: a hash route for an
 * existing page/category, or a non-navigating red link when missing. */
export function wireWikilinks(root, resolve) {
  if (!root) return;
  for (const a of root.querySelectorAll('a.wikilink')) {
    if (a.dataset.wired) continue;
    a.dataset.wired = '1';
    const r = resolve(a.dataset.target);
    if (r.kind === 'page') {
      a.setAttribute('href', `#/${r.slug}`);
    } else if (r.kind === 'category') {
      a.setAttribute('href', `#/category/${encodeURIComponent(r.name)}`);
    } else {
      a.classList.add('is-missing');
      a.setAttribute('title', `${a.dataset.target} (page does not exist)`);
      a.removeAttribute('href');
    }
  }
}
