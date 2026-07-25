// Wikitext → HTML mini-parser for the M5.1 Fandom Preview app (STU-647).
//
// Primary scope is the subset `scripts/wiki_export.py` emits — a frozen target
// (core wikitext hasn't changed since ~2016) coupled to our own exporter. When
// the exporter grows a construct, the STU-645 fixture breaks and this module
// changes in the same PR.
//
// It also renders the hand-authored *reference* pages (the `real-wiki/`
// Fandom captures) the preview now carries alongside generated ones: source-less
// Fandom templates ({{Infobox …}} without a local source, {{Q}} pull-quotes,
// {{Clr}} clears), [[File:…]]/<gallery> media (rendered as captioned
// placeholders — the images aren't committed), [external links] and [[xx:…]]
// interlanguage links. These are best-effort, not MediaWiki-faithful.
//
// Constructs: headings, bold/italic, [[wikilinks]] (+ [[t|label]], [[:Category:…]]),
// [[Category:X]] tags (collected, not rendered inline), {| … |} tables,
// {{Infobox …}} calls (expanded against a local template source, or rendered
// generically from their args when none exists), {{Q}}/{{Clr}} Fandom templates,
// [[File:…]] media placeholders, [external] links, native
// <div>/<span class="mw-collapsible"> spoiler markup (passed through, inner
// wikitext still parsed), and <ref>…</ref> footnotes collected into a
// <references/> list (STU-656).

/** Render one page's wikitext.
 * @param {string} source raw wikitext
 * @param {{templates?: Record<string,string>, title?: string}} [opts]
 *   `templates`: template name → source
 *   (e.g. {"Infobox character": "<includeonly>{| … |}</includeonly>"}).
 *   `title`: page title, used as the header of a source-less generic infobox.
 * @returns {{html: string, categories: string[]}}
 */
export function renderWikitext(source, { templates = {}, title = '' } = {}) {
  const expanded = expandTemplates(source ?? '', templates, title);
  const { body, categories } = extractCategories(expanded);
  const refs = [];
  const withMarkers = collectRefs(body, refs);
  return { html: renderBlocks(withMarkers, refs), categories };
}

// --- footnotes (STU-656) ---------------------------------------------------

/** Replace each `<ref>…</ref>` with a numbered superscript marker, collecting
 * its text into `refs` (rendered later at `<references/>`). Coupled to the
 * exporter's plain `<ref>` form; the citation body is plain text (book title +
 * chapter), so it is stored raw and inline-rendered when the list is built. */
function collectRefs(src, refs) {
  return src.replace(/<ref>([\s\S]*?)<\/ref>/g, (_m, inner) => {
    refs.push(inner.trim());
    const n = refs.length;
    return `<sup class="reference"><a class="ref-marker" data-note="${n}">[${n}]</a></sup>`;
  });
}

/** Render the collected footnotes as an ordered list. Empty when the page has
 * no `<ref>` — a bare `<references/>` then renders nothing, as in MediaWiki. */
function renderReflist(refs) {
  if (!refs.length) return '';
  const items = refs
    .map((r, i) => `<li id="cite_note-${i + 1}">${renderInline(r)}</li>`)
    .join('');
  return `<ol class="references">${items}</ol>`;
}

// --- template expansion ----------------------------------------------------

/** Replace each `{{Name|k=v|…}}` call with its expanded body. A registered
 * template expands against its source; well-known source-less Fandom templates
 * (Infobox/Q/Clr) render generically; any other unknown call is left verbatim
 * unless it is bare (no args) — a bare `{{Navbox}}` we can't render is dropped
 * rather than leaked as raw braces. Never throws. */
export function expandTemplates(source, templates, title = '') {
  return source.replace(/\{\{([^]*?)\}\}/g, (whole, inner) => {
    const parts = splitTopLevel(inner, '|');
    const name = parts[0].trim();
    const args = {};
    const positional = [];
    for (let k = 1; k < parts.length; k++) {
      const eq = parts[k].indexOf('=');
      if (eq === -1) { positional.push(parts[k].trim()); continue; }
      args[parts[k].slice(0, eq).trim()] = parts[k].slice(eq + 1).trim();
    }
    const tpl = templates[name];
    if (tpl != null) return substituteTemplate(tpl, args);
    if (/^infobox\b/i.test(name)) return genericInfobox(name, args, title);
    if (/^(q|quote|cquote)$/i.test(name)) return quoteBlock(positional, args);
    if (/^clr/i.test(name)) return '\n<div class="clear"></div>\n';
    // Unknown: keep it verbatim if it carried data (might be meaningful);
    // drop a bare `{{Navbox}}` that would only leak raw braces.
    return positional.length || Object.keys(args).length ? whole : '';
  });
}

/** Render a source-less `{{Infobox …}}` from its raw args as the standard
 * infobox table: a title header, an image placeholder row, then one label/value
 * row per non-empty field. Emits wikitext so the existing table renderer and CSS
 * apply unchanged. */
function genericInfobox(name, args, title) {
  const rows = ['|-', `! colspan="2" | ${title || name}`];
  const image = args.image ? firstImageName(args.image) : null;
  if (image) rows.push('|-', `| colspan="2" class="infobox-image" | [[File:${image}]]`);
  for (const [k, v] of Object.entries(args)) {
    if (k === 'image' || !v) continue;
    rows.push('|-', `| '''${capitalize(k)}''' || ${v}`);
  }
  return `\n{| class="infobox"\n${rows.join('\n')}\n|}\n`;
}

/** `{{Q|quote|author}}` (or |quote=/|author=) → an italic pull-quote block. */
function quoteBlock(positional, args) {
  const text = args.quote || args.text || positional[0] || '';
  const author = args.author || args.cite || positional[1] || '';
  const cite = author ? `\n<span class="quote-cite">— ${author}</span>` : '';
  return `\n<div class="pullquote">\n''${text}''${cite}\n</div>\n`;
}

/** First image filename inside an infobox `image=` value — a bare `X.jpg`, a
 * `[[File:X.jpg|…]]` embed, or the first entry of a `<gallery>`. */
function firstImageName(value) {
  const gallery = value.match(/<gallery[^>]*>([\s\S]*?)(?:<\/gallery>|$)/i);
  const scope = gallery ? gallery[1] : value;
  const line = scope
    .split('\n')
    .map((s) => s.trim())
    .find((s) => /\.(jpe?g|png|gif|svg|webp)/i.test(s));
  if (!line) return null;
  const name = line.replace(/^\[\[(?:File|Image):/i, '').split('|')[0].trim();
  return name || null;
}

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Substitute `{{{param|default}}}` placeholders, dropping <includeonly>. */
function substituteTemplate(tpl, args) {
  const t = tpl.replace(/<\/?includeonly>/g, '');
  return t
    .replace(/\{\{\{([^|}]+)(?:\|([^}]*))?\}\}\}/g, (_m, key, def) => {
      const v = args[key.trim()];
      if (v != null && v !== '') return v;
      return def != null ? def : '';
    })
    .trim();
}

/** Split on `sep` (any length), but not inside `[[ … ]]` — a piped wikilink or
 * a `||` cell separator that sits inside a link is one value. */
function splitTopLevel(s, sep) {
  const out = [];
  let buf = '';
  let depth = 0;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '[' && s[i + 1] === '[') { depth++; buf += '[['; i++; continue; }
    if (s[i] === ']' && s[i + 1] === ']') { depth = Math.max(0, depth - 1); buf += ']]'; i++; continue; }
    if (depth === 0 && s.startsWith(sep, i)) { out.push(buf); buf = ''; i += sep.length - 1; continue; }
    buf += s[i];
  }
  out.push(buf);
  return out;
}

// --- categories ------------------------------------------------------------

/** Pull standalone `[[Category:X]]` tag lines out of the body. Inline
 * `[[:Category:X|label]]` links (leading colon) are left as links. */
function extractCategories(src) {
  const categories = [];
  const kept = src.split('\n').filter((line) => {
    const m = line.match(/^\[\[Category:([^\]]+)\]\]\s*$/);
    if (m) { categories.push(m[1].trim()); return false; }
    // Drop [[xx:Title]] interlanguage links (lowercase lang prefix) — no target here.
    if (/^\[\[[a-z]{2,3}:[^\]]+\]\]\s*$/.test(line)) return false;
    return true;
  });
  return { body: kept.join('\n'), categories };
}

// --- block rendering -------------------------------------------------------

function renderBlocks(body, refs = []) {
  const lines = body.split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === '') { i++; continue; }

    if (/^<references\s*\/?>$/.test(line.trim())) {
      out.push(renderReflist(refs));
      i++;
      continue;
    }
    if (line.startsWith('{|')) {
      const j = findLine(lines, i + 1, (l) => l.startsWith('|}'));
      out.push(renderTable(lines.slice(i, j + 1)));
      i = j + 1;
      continue;
    }
    if (/^<div\b[^>]*>\s*<\/div>$/.test(line.trim())) {
      out.push(line.trim());
      i++;
      continue;
    }
    if (/^<div\b/.test(line)) {
      const j = findLine(lines, i + 1, (l) => l.trim() === '</div>');
      const inner = lines.slice(i + 1, j).join('\n');
      out.push(`${line}\n${renderBlocks(inner, refs)}\n</div>`);
      i = j + 1;
      continue;
    }
    const h = line.match(/^(={1,6})\s*(.*?)\s*\1\s*$/);
    if (h) {
      const level = h[1].length;
      out.push(`<h${level}>${renderInline(h[2])}</h${level}>`);
      i++;
      continue;
    }
    if (line.startsWith('* ')) {
      const items = [];
      while (i < lines.length && lines[i].startsWith('* ')) { items.push(lines[i].slice(2)); i++; }
      out.push('<ul>' + items.map((it) => `<li>${renderInline(it)}</li>`).join('') + '</ul>');
      continue;
    }
    const para = [];
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !lines[i].startsWith('{|') &&
      !/^<div\b/.test(lines[i]) &&
      !/^(={1,6})\s*.*\s*\1\s*$/.test(lines[i]) &&
      !/^<references\s*\/?>$/.test(lines[i].trim()) &&
      !lines[i].startsWith('* ')
    ) {
      para.push(lines[i]);
      i++;
    }
    out.push(`<p>${renderInline(para.join(' '))}</p>`);
  }
  return out.join('\n');
}

function findLine(lines, start, pred) {
  for (let k = start; k < lines.length; k++) if (pred(lines[k])) return k;
  return lines.length - 1;
}

// --- tables ----------------------------------------------------------------

function renderTable(lines) {
  const attrs = lines[0].slice(2).trim(); // after '{|'
  const rows = [];
  let cur = null;
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith('|}')) break;
    if (line.startsWith('|-')) { if (cur) rows.push(cur); cur = []; continue; }
    if (line.startsWith('!') || line.startsWith('|')) {
      if (!cur) cur = [];
      const isHeader = line.startsWith('!');
      const cells = splitTopLevel(line.slice(1), isHeader ? '!!' : '||');
      for (const cell of cells) cur.push({ header: isHeader, ...parseCell(cell) });
    }
  }
  if (cur) rows.push(cur);

  let html = `<table${attrs ? ' ' + attrs : ''}>`;
  for (const row of rows) {
    html += '<tr>';
    for (const c of row) {
      const tag = c.header ? 'th' : 'td';
      html += `<${tag}${c.attrs ? ' ' + c.attrs : ''}>${renderInline(c.content.trim())}</${tag}>`;
    }
    html += '</tr>';
  }
  return html + '</table>';
}

/** A cell may lead with HTML attributes separated from content by a single `|`
 * (`colspan="2" | Alice`). Otherwise the whole cell is content. */
function parseCell(cell) {
  const m = cell.match(/^\s*([a-zA-Z-]+="[^"]*"(?:\s+[a-zA-Z-]+="[^"]*")*)\s*\|(.*)$/s);
  if (m) return { attrs: m[1], content: m[2] };
  return { attrs: '', content: cell };
}

// --- inline ----------------------------------------------------------------

/** Inline markup. Existing HTML tags (our mw-collapsible spans/divs) pass
 * through verbatim; only the text between tags is escaped and wiki-transformed.
 * File embeds run first (before wikilinks, which would otherwise swallow the
 * `[[File:…]]` syntax). */
function renderInline(str) {
  return str
    .split(/(<[^>]+>)/)
    .map((part, idx) => {
      if (idx % 2 === 1) return part; // an HTML tag
      let t = escapeText(part);
      t = renderFileEmbeds(t);
      t = renderExternalLinks(t);
      return inlineFmt(t);
    })
    .join('');
}

/** Wikilinks + bold/italic. Assumes its input is already escaped and free of
 * File/external syntax (renderInline handles those first). */
function inlineFmt(t) {
  t = renderWikilinks(t);
  t = t.replace(/'''(.+?)'''/g, '<strong>$1</strong>');
  t = t.replace(/''(.+?)''/g, '<em>$1</em>');
  return t;
}

/** `[[File:name|opts…|caption]]` / `[[Image:…]]` → a floated captioned
 * placeholder (the referenced images aren't committed). MediaWiki keyword opts
 * (alignment/format/size) set the float; the remaining param is the caption. */
function renderFileEmbeds(t) {
  return t.replace(/\[\[(?:File|Image):([^\]]+)\]\]/gi, (_m, body) => {
    const parts = body.split('|').map((s) => s.trim());
    const name = parts.shift();
    let align = '';
    const rest = [];
    for (const p of parts) {
      if (/^(left|right|center|none)$/i.test(p)) align = p.toLowerCase();
      else if (/^(thumb|thumbnail|frame|frameless|border)$/i.test(p)) continue;
      else if (/^(\d+x?\d*px|x\d+px|upright(=[\d.]+)?)$/i.test(p)) continue;
      else if (p) rest.push(p);
    }
    const cls = `wikithumb${align ? ` t${align}` : ''}`;
    const caption = rest.length ? `<span class="thumbcaption">${inlineFmt(rest[rest.length - 1])}</span>` : '';
    return `<span class="${cls}"><span class="thumbimage" title="${name}">${name}</span>${caption}</span>`;
  });
}

/** Single-bracket external link `[https://… label]` (or bare `[https://…]`). */
function renderExternalLinks(t) {
  return t.replace(/\[(https?:\/\/[^\s\]]+)(?:\s+([^\]]*))?\]/g, (_m, url, label) => {
    const text = label && label.trim() ? inlineFmt(label.trim()) : '↗';
    return `<a class="external" href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`;
  });
}

function renderWikilinks(text) {
  return text.replace(/\[\[([^\]|]+?)(?:\|([^\]]*?))?\]\]/g, (_m, target, label) => {
    const t = target.trim();
    const display = label != null && label !== '' ? label : t;
    return `<a class="wikilink" data-target="${escapeAttr(t)}">${display}</a>`;
  });
}

function escapeText(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function escapeAttr(s) {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}
