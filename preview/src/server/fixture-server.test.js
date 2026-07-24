import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { describe, it, expect } from 'vitest';

import { buildIndex, loadTemplates, readPage } from './fixture-server.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(HERE, '../../../tests/fixtures/preview/output');

describe('buildIndex', () => {
  const index = buildIndex(FIXTURE, '01-alice-in-wonderland');
  const byPath = Object.fromEntries(index.pages.map((p) => [p.path, p]));

  it('carries the book id', () => {
    expect(index.book).toBe('01-alice-in-wonderland');
  });

  it('lists Main_Page first', () => {
    expect(index.pages[0].path).toBe('Main_Page.wiki');
  });

  it('maps subdirs to entity types', () => {
    expect(byPath['characters/Alice.wiki'].entityType).toBe('PERSON');
    expect(byPath['locations/Wonderland.wiki'].entityType).toBe('PLACE');
    expect(byPath['organizations/Court_of_Hearts.wiki'].entityType).toBe('ORG');
    expect(byPath['events/A_Mad_Tea-Party.wiki'].entityType).toBe('EVENT');
    expect(byPath['Synopsis.wiki'].entityType).toBeNull();
  });

  it('derives title and a unique slug', () => {
    expect(byPath['characters/Alice.wiki'].title).toBe('Alice');
    expect(byPath['characters/Alice.wiki'].slug).toBe('characters/Alice');
    expect(byPath['Minor_Characters.wiki'].title).toBe('Minor Characters');
  });

  it('excludes the templates dir', () => {
    expect(index.pages.some((p) => p.path.startsWith('templates/'))).toBe(false);
  });
});

describe('loadTemplates', () => {
  it('keys template sources by name (filename `_` → space)', () => {
    const tpl = loadTemplates(FIXTURE);
    expect(tpl['Infobox character']).toContain('{{{name}}}');
    expect(tpl['Infobox location']).toBeTypeOf('string');
  });
});

describe('readPage', () => {
  it('returns raw wikitext', () => {
    expect(readPage(FIXTURE, 'characters/Alice.wiki')).toContain('{{Infobox character');
  });

  it('rejects path traversal', () => {
    expect(() => readPage(FIXTURE, '../../../etc/passwd')).toThrow();
    expect(() => readPage(FIXTURE, '/etc/passwd')).toThrow();
  });
});
