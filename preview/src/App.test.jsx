// @vitest-environment jsdom
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup, act } from '@testing-library/react';

import App from './App.jsx';
import { buildIndex, loadTemplates, readPage } from './server/fixture-server.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(HERE, '../../tests/fixtures/preview/output');
const BOOK = '01-alice-in-wonderland';

const jsonRes = (body) => ({ ok: true, json: async () => body });
const textRes = (body) => ({ ok: true, text: async () => body });

beforeEach(() => {
  window.location.hash = '';
  global.fetch = vi.fn(async (url) => {
    const u = new URL(url, 'http://localhost');
    if (u.pathname === '/api/index.json') return jsonRes(buildIndex(FIXTURE, BOOK));
    if (u.pathname === '/api/templates.json') return jsonRes(loadTemplates(FIXTURE));
    if (u.pathname === '/api/page') return textRes(readPage(FIXTURE, u.searchParams.get('path')));
    throw new Error(`unexpected fetch ${url}`);
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('App shell', () => {
  it('builds the sidebar nav grouped by type', async () => {
    render(<App />);
    expect(await screen.findByText('Characters')).toBeTruthy();
    expect(screen.getByText('Locations')).toBeTruthy();
    // a character link is present
    expect(screen.getByRole('link', { name: 'Alice' })).toBeTruthy();
  });

  it('renders the Main_Page landing page by default', async () => {
    render(<App />);
    // Main_Page body has the "Main characters" heading (chrome, lang=en)
    expect(await screen.findByRole('heading', { name: 'Main characters' })).toBeTruthy();
  });

  it('renders a character page (infobox + body) for its hash route', async () => {
    window.location.hash = '#/characters/Alice';
    render(<App />);
    // body prose + parsed heading
    expect(await screen.findByRole('heading', { name: 'Biography', level: 2 })).toBeTruthy();
    // the infobox table expanded from {{Infobox character}}
    const infobox = document.querySelector('table.infobox');
    expect(infobox).toBeTruthy();
    expect(infobox.textContent).toContain('Human'); // species value
    // categories footer
    expect(screen.getByText('Categories:')).toBeTruthy();
  });

  it('navigates when the hash changes', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: 'Main characters' });
    await act(async () => {
      window.location.hash = '#/locations/Wonderland';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Overview', level: 2 })).toBeTruthy(),
    );
  });

  it('shows an error state when the index fails to load', async () => {
    global.fetch = vi.fn(async () => ({ ok: false, status: 500 }));
    render(<App />);
    expect(await screen.findByText(/Failed to load the wiki/)).toBeTruthy();
  });
});
