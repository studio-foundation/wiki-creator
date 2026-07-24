// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';

import { buildResolver, wireWikilinks } from './wikilinks.js';

const PAGES = [
  { title: 'Alice', slug: 'characters/Alice', categories: ['Characters'] },
  { title: 'White Rabbit', slug: 'characters/White_Rabbit', categories: [] },
  { title: 'Wonderland', slug: 'locations/Wonderland', categories: [] },
  { title: 'Synopsis', slug: 'Synopsis', categories: [] },
];

describe('buildResolver', () => {
  const resolve = buildResolver(PAGES);

  it('resolves an exact title to its page slug', () => {
    expect(resolve('Wonderland')).toEqual({ kind: 'page', slug: 'locations/Wonderland' });
    expect(resolve('White Rabbit')).toEqual({ kind: 'page', slug: 'characters/White_Rabbit' });
  });

  it('is first-letter case-insensitive and treats _ as space (MediaWiki)', () => {
    expect(resolve('wonderland')).toEqual({ kind: 'page', slug: 'locations/Wonderland' });
    expect(resolve('White_Rabbit')).toEqual({ kind: 'page', slug: 'characters/White_Rabbit' });
  });

  it('resolves a category target (with or without leading colon)', () => {
    expect(resolve(':Category:Characters')).toEqual({ kind: 'category', name: 'Characters' });
    expect(resolve('Category:Main Characters')).toEqual({ kind: 'category', name: 'Main Characters' });
  });

  it('reports a missing page (red link)', () => {
    expect(resolve('Dormouse')).toEqual({ kind: 'missing' });
  });
});

describe('wireWikilinks', () => {
  function render(html) {
    const root = document.createElement('div');
    root.innerHTML = html;
    wireWikilinks(root, buildResolver(PAGES));
    return root;
  }

  it('gives an existing page link a hash route', () => {
    const a = render('<a class="wikilink" data-target="Wonderland">Wonderland</a>').querySelector('a');
    expect(a.getAttribute('href')).toBe('#/locations/Wonderland');
    expect(a.classList.contains('is-missing')).toBe(false);
  });

  it('routes a category link and encodes the name', () => {
    const a = render('<a class="wikilink" data-target=":Category:Main Characters">x</a>').querySelector('a');
    expect(a.getAttribute('href')).toBe('#/category/Main%20Characters');
  });

  it('marks a dangling link as a non-navigating red link', () => {
    const a = render('<a class="wikilink" data-target="Dormouse">Dormouse</a>').querySelector('a');
    expect(a.classList.contains('is-missing')).toBe(true);
    expect(a.hasAttribute('href')).toBe(false);
    expect(a.getAttribute('title')).toContain('does not exist');
  });

  it('is idempotent', () => {
    const root = render('<a class="wikilink" data-target="Alice">Alice</a>');
    wireWikilinks(root, buildResolver(PAGES));
    expect(root.querySelector('a').getAttribute('href')).toBe('#/characters/Alice');
  });
});
