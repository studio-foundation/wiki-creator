// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';

import { wireCollapsibles } from './collapsible.js';

function fixture() {
  const root = document.createElement('div');
  root.innerHTML =
    '<div class="mw-collapsible mw-collapsed" data-expandtext="Chapter 12 — reveal" ' +
    'data-collapsetext="Hide"><h2>Narrative role</h2><p>spoiler</p></div>';
  return root;
}

describe('wireCollapsibles', () => {
  it('adds a toggle and starts collapsed', () => {
    const root = fixture();
    wireCollapsibles(root);
    const block = root.querySelector('.mw-collapsible');
    const toggle = block.querySelector('.wiki-collapsible-toggle');
    expect(toggle).toBeTruthy();
    expect(toggle.textContent).toBe('Chapter 12 — reveal');
    expect(block.classList.contains('is-collapsed')).toBe(true);
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    // content is wrapped so it can be hidden as one unit (incl. bare text nodes)
    const content = block.querySelector('.wiki-collapsible-content');
    expect(content).toBeTruthy();
    expect(content.querySelector('h2').textContent).toBe('Narrative role');
  });

  it('expands and collapses on click', () => {
    const root = fixture();
    wireCollapsibles(root);
    const block = root.querySelector('.mw-collapsible');
    const toggle = block.querySelector('.wiki-collapsible-toggle');

    toggle.click();
    expect(block.classList.contains('is-collapsed')).toBe(false);
    expect(toggle.textContent).toBe('Hide');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');

    toggle.click();
    expect(block.classList.contains('is-collapsed')).toBe(true);
    expect(toggle.textContent).toBe('Chapter 12 — reveal');
  });

  it('is idempotent (no double-wiring)', () => {
    const root = fixture();
    wireCollapsibles(root);
    wireCollapsibles(root);
    expect(root.querySelectorAll('.wiki-collapsible-toggle')).toHaveLength(1);
  });
});
