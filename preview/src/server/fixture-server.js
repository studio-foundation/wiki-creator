// Dev stand-in for the STU-646 launcher: build the page index and serve the
// raw wikitext + infobox templates from a book's exported `output/` dir.
//
// These are pure functions over the filesystem, reused by the Vite dev
// middleware (preview/vite.config.js) and by the tests. When STU-646 lands as
// the Python launcher, it serves the SAME shape on the same routes and becomes
// the source of truth; this stays as the standalone `npm run dev` data source.

import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

/** Export subdir → entity type (mirrors base.yaml#entity_types.export.subdir). */
const SUBDIR_TYPE = {
  characters: 'PERSON',
  locations: 'PLACE',
  organizations: 'ORG',
  events: 'EVENT',
  factions: 'FACTION',
};

/** Filename stem → display title (`_` → space). */
function titleOf(stem) {
  return stem.replace(/_/g, ' ');
}

function listWiki(dir, sub = '') {
  const out = [];
  for (const e of readdirSync(join(dir, sub), { withFileTypes: true })) {
    const rel = sub ? `${sub}/${e.name}` : e.name;
    if (e.isDirectory()) out.push(...listWiki(dir, rel));
    else if (e.name.endsWith('.wiki')) out.push(rel);
  }
  return out;
}

/** The page index a book's `output/` exposes.
 * @returns {{book: string, pages: Array<{title,path,slug,entityType,subdir}>}}
 */
export function buildIndex(outputDir, book = '') {
  const pages = listWiki(outputDir)
    .filter((p) => !p.startsWith('templates/')) // templates are not pages
    .map((path) => {
      const slash = path.lastIndexOf('/');
      const subdir = slash === -1 ? '' : path.slice(0, slash);
      const stem = path.slice(slash + 1).replace(/\.wiki$/, '');
      return {
        title: titleOf(stem),
        path,
        slug: path.replace(/\.wiki$/, ''), // stable route key, unique per file
        entityType: SUBDIR_TYPE[subdir] ?? null,
        subdir,
      };
    });
  // Main_Page first, then a stable order by path.
  pages.sort((a, b) => {
    if (a.path === 'Main_Page.wiki') return -1;
    if (b.path === 'Main_Page.wiki') return 1;
    return a.path.localeCompare(b.path);
  });
  return { book, pages };
}

/** templates/*.wiki → { "Infobox character": "<source>" } (filename `_` → space). */
export function loadTemplates(outputDir) {
  const dir = join(outputDir, 'templates');
  const map = {};
  for (const f of readdirSync(dir)) {
    if (!f.endsWith('.wiki')) continue;
    map[f.replace(/\.wiki$/, '').replace(/_/g, ' ')] = readFileSync(join(dir, f), 'utf-8');
  }
  return map;
}

/** Raw wikitext for one page path. Throws if the path escapes the output dir. */
export function readPage(outputDir, path) {
  if (path.includes('..') || path.startsWith('/')) throw new Error(`bad path: ${path}`);
  return readFileSync(join(outputDir, path), 'utf-8');
}
