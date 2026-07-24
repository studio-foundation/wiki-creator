// Wikitext → HTML mini-parser for the M5.1 Fandom Preview app (STU-647).
//
// Scope is deliberately narrow: it renders *only* the subset that
// `scripts/wiki_export.py` emits, not arbitrary wikitext. That subset is a
// frozen target (core wikitext hasn't changed since ~2016) and the input is our
// own trusted exporter output, so the parser is coupled to our export code —
// not to MediaWiki. When the exporter grows a construct, the STU-645 fixture
// breaks and this module changes in the same PR.
//
// Constructs: headings, bold/italic, [[wikilinks]] (+ [[t|label]], [[:Category:…]]),
// [[Category:X]] tags (collected, not rendered inline), {| … |} tables,
// {{Infobox …}} calls expanded against local template sources, and native
// <div>/<span class="mw-collapsible"> spoiler markup (passed through, inner
// wikitext still parsed).

/** Render one page's wikitext.
 * @param {string} source raw wikitext
 * @param {{templates?: Record<string,string>}} [opts] template name → source
 *   (e.g. {"Infobox character": "<includeonly>{| … |}</includeonly>"})
 * @returns {{html: string, categories: string[]}}
 */
export function renderWikitext(source, { templates = {} } = {}) {
  const expanded = expandTemplates(source ?? '', templates);
  const { body, categories } = extractCategories(expanded);
  return { html: renderBlocks(body), categories };
}

// --- template expansion ----------------------------------------------------

/** Replace each `{{Name|k=v|…}}` call with its expanded template body. An
 * unknown template is left verbatim (graceful, never throws). */
export function expandTemplates(source, templates) {
  return source.replace(/\{\{([^]*?)\}\}/g, (whole, inner) => {
    const parts = splitTopLevel(inner, '|');
    const name = parts[0].trim();
    const tpl = templates[name];
    if (tpl == null) return whole;
    const args = {};
    for (let k = 1; k < parts.length; k++) {
      const eq = parts[k].indexOf('=');
      if (eq === -1) continue;
      args[parts[k].slice(0, eq).trim()] = parts[k].slice(eq + 1).trim();
    }
    return substituteTemplate(tpl, args);
  });
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
    return true;
  });
  return { body: kept.join('\n'), categories };
}

// --- block rendering -------------------------------------------------------

function renderBlocks(body) {
  const lines = body.split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === '') { i++; continue; }

    if (line.startsWith('{|')) {
      const j = findLine(lines, i + 1, (l) => l.startsWith('|}'));
      out.push(renderTable(lines.slice(i, j + 1)));
      i = j + 1;
      continue;
    }
    if (/^<div\b/.test(line)) {
      const j = findLine(lines, i + 1, (l) => l.trim() === '</div>');
      const inner = lines.slice(i + 1, j).join('\n');
      out.push(`${line}\n${renderBlocks(inner)}\n</div>`);
      i = j + 1;
      continue;
    }
    const h = line.match(/^(={1,6})\s+(.*?)\s+\1\s*$/);
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
      !/^={1,6}\s/.test(lines[i]) &&
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
 * through verbatim; only the text between tags is escaped and wiki-transformed. */
function renderInline(str) {
  return str
    .split(/(<[^>]+>)/)
    .map((part, idx) => {
      if (idx % 2 === 1) return part; // an HTML tag
      let t = escapeText(part);
      t = renderWikilinks(t);
      t = t.replace(/'''(.+?)'''/g, '<strong>$1</strong>');
      t = t.replace(/''(.+?)''/g, '<em>$1</em>');
      return t;
    })
    .join('');
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
