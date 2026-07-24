import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { describe, it, expect } from 'vitest';

import { renderWikitext, expandTemplates } from './parse.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(HERE, '../../../tests/fixtures/preview/output');

const read = (rel) => readFileSync(join(FIXTURE, rel), 'utf-8');

/** templates/ files → { "Infobox character": "<source>" } (name = filename, `_`→space). */
function loadTemplates() {
  const dir = join(FIXTURE, 'templates');
  const map = {};
  for (const f of readdirSync(dir)) {
    if (!f.endsWith('.wiki')) continue;
    map[f.replace(/\.wiki$/, '').replace(/_/g, ' ')] = readFileSync(join(dir, f), 'utf-8');
  }
  return map;
}

const TEMPLATES = loadTemplates();
const render = (rel) => renderWikitext(read(rel), { templates: TEMPLATES });

describe('headings', () => {
  it('renders = … = through ==== … ==== at the right level', () => {
    const { html } = renderWikitext('= T =\n\n== A ==\n\n=== B ===\n\n==== C ====');
    expect(html).toContain('<h1>T</h1>');
    expect(html).toContain('<h2>A</h2>');
    expect(html).toContain('<h3>B</h3>');
    expect(html).toContain('<h4>C</h4>');
  });

  it('renders the fixture section headings', () => {
    expect(render('characters/Alice.wiki').html).toContain('<h2>Biography</h2>');
  });
});

describe('inline formatting', () => {
  it('bold and italic', () => {
    const { html } = renderWikitext("'''bold''' and ''italic''");
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<em>italic</em>');
  });

  it('escapes stray angle brackets in text but keeps real HTML tags', () => {
    const { html } = renderWikitext('a < b\n\n<span class="x">kept</span>');
    expect(html).toContain('a &lt; b');
    expect(html).toContain('<span class="x">kept</span>');
  });
});

describe('wikilinks', () => {
  it('[[Target]] and [[Target|label]]', () => {
    const { html } = renderWikitext('see [[Wonderland]] and [[Synopsis|the synopsis]]');
    expect(html).toContain('<a class="wikilink" data-target="Wonderland">Wonderland</a>');
    expect(html).toContain('<a class="wikilink" data-target="Synopsis">the synopsis</a>');
  });

  it('carries the raw target so resolution/red-links can happen downstream (STU-650)', () => {
    // Dormouse has no page in the fixture — the parser still emits the link with
    // its target; red-link styling is the wikilinks issue's job, not the parser's.
    const { html } = render('characters/Alice.wiki');
    expect(html).toContain('data-target="Dormouse"');
    expect(html).toContain('data-target="Wonderland"'); // cross-subdir (a PLACE)
  });

  it('[[:Category:X|label]] navigation links survive (not treated as category tags)', () => {
    const { html } = render('Main_Page.wiki');
    expect(html).toContain('data-target=":Category:Characters"');
  });
});

describe('category tags', () => {
  it('collects [[Category:X]] out of the body', () => {
    const { html, categories } = render('characters/Alice.wiki');
    expect(categories).toContain('Characters');
    expect(categories).toContain('Main Characters');
    expect(html).not.toContain('[[Category:'); // removed from rendered body
  });
});

describe('infobox template expansion', () => {
  it('expands {{Infobox character|…}} against the local template source', () => {
    const { html } = render('characters/Alice.wiki');
    expect(html).toContain('<table class="infobox">');
    expect(html).toContain('<th colspan="2">Alice</th>'); // name row
    expect(html).toContain('Human'); // species value
    // the French template row label is preserved (labels are hard-coded in base.yaml)
    expect(html).toContain('<strong>Statut</strong>');
  });

  it('substitutes {{{param|default}}} and drops empty values', () => {
    const src = '{{Infobox character|name=Bob|status=Alive}}';
    const tpl =
      '<includeonly>\n{| class="infobox"\n|-\n! colspan="2" | {{{name}}}\n|-\n' +
      "| '''Statut''' || {{{status|}}}\n|-\n| '''Espèce''' || {{{species|}}}\n|}\n</includeonly>";
    const { html } = renderWikitext(src, { templates: { 'Infobox character': tpl } });
    expect(html).toContain('<th colspan="2">Bob</th>');
    expect(html).toContain('Alive');
    expect(html).toContain('<strong>Espèce</strong>'); // row kept, value cell empty
  });

  it('leaves an unknown template verbatim instead of throwing', () => {
    const { html } = renderWikitext('{{Unknown|a=1}}', { templates: {} });
    expect(html).toContain('{{Unknown|a=1}}');
  });

  it('keeps a piped wikilink inside an infobox value intact', () => {
    const src = '{{Infobox character|name=X|affiliation=[[Court of Hearts|the Court]]}}';
    const tpl =
      '<includeonly>\n{| class="infobox"\n|-\n! colspan="2" | {{{name}}}\n|-\n' +
      "| '''Affiliation''' || {{{affiliation|}}}\n|}\n</includeonly>";
    const { html } = renderWikitext(src, { templates: { 'Infobox character': tpl } });
    expect(html).toContain('<a class="wikilink" data-target="Court of Hearts">the Court</a>');
  });
});

describe('mw-collapsible spoiler markup', () => {
  it('passes the section div through and still parses its inner wikitext', () => {
    const { html } = render('characters/Alice.wiki');
    expect(html).toContain('<div class="mw-collapsible mw-collapsed"');
    expect(html).toContain('data-expandtext="Chapter 12 — reveal"');
    expect(html).toContain('<h2>Narrative role</h2>'); // inner heading parsed
  });

  it('keeps a gated inline infobox value span', () => {
    const { html } = render('characters/Queen_of_Hearts.wiki');
    expect(html).toContain('<span class="mw-collapsible mw-collapsed"');
    expect(html).toContain('Dissolved when Alice wakes'); // gated death value
  });
});

describe('lists', () => {
  it('renders * bullets as a <ul>', () => {
    const { html } = render('Minor_Characters.wiki');
    expect(html).toContain('<ul>');
    expect(html).toContain('<li><strong>Dodo</strong> — organiser of the Caucus-race.</li>');
  });
});

describe('body-only pages', () => {
  it('SYNOPSIS and COLLATION render with no infobox', () => {
    expect(render('Synopsis.wiki').html).not.toContain('class="infobox"');
    expect(render('Minor_Characters.wiki').html).not.toContain('class="infobox"');
  });
});

describe('whole-fixture robustness', () => {
  const pages = [];
  const walk = (rel) => {
    for (const e of readdirSync(join(FIXTURE, rel), { withFileTypes: true })) {
      const child = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) walk(child);
      else if (e.name.endsWith('.wiki') && !child.startsWith('templates/')) pages.push(child);
    }
  };
  walk('');

  it('renders every fixture page without throwing and produces no raw {{ }} / [[Category', () => {
    expect(pages.length).toBeGreaterThan(8);
    for (const p of pages) {
      const { html } = render(p);
      expect(html, p).not.toMatch(/\{\{Infobox/); // every infobox call expanded
      expect(html, p).not.toContain('[[Category:'); // every category tag collected
    }
  });
});

describe('expandTemplates (unit)', () => {
  it('is a no-op when there are no calls', () => {
    expect(expandTemplates('plain text', {})).toBe('plain text');
  });
});
