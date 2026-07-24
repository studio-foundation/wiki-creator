import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { buildIndex, loadTemplates, readPage } from './src/server/fixture-server.js';

const HERE = dirname(fileURLToPath(import.meta.url));
// STU-648 develops against the STU-645 fixture. Override with WIKI_PREVIEW_OUTPUT
// (the STU-646 launcher will point here at a real book's output/ dir).
const OUTPUT_DIR =
  process.env.WIKI_PREVIEW_OUTPUT || join(HERE, '../tests/fixtures/preview/output');
const BOOK = process.env.WIKI_PREVIEW_BOOK || '01-alice-in-wonderland';

function json(res, body) {
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(body));
}

/** Dev/preview stand-in for the STU-646 launcher: serves the page index,
 * infobox templates and raw wikitext from OUTPUT_DIR on the /api routes the
 * app fetches. Replaced by the Python launcher in production. */
function fixtureApi() {
  const middleware = (req, res, next) => {
    try {
      const url = new URL(req.url, 'http://localhost');
      if (url.pathname === '/api/index.json') return json(res, buildIndex(OUTPUT_DIR, BOOK));
      if (url.pathname === '/api/templates.json') return json(res, loadTemplates(OUTPUT_DIR));
      if (url.pathname === '/api/page') {
        const path = url.searchParams.get('path') || '';
        res.setHeader('Content-Type', 'text/plain; charset=utf-8');
        return res.end(readPage(OUTPUT_DIR, path));
      }
    } catch (err) {
      res.statusCode = 404;
      return json(res, { error: String(err) });
    }
    next();
  };
  return {
    name: 'wiki-preview-fixture-api',
    configureServer(server) {
      server.middlewares.use(middleware);
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware);
    },
  };
}

export default defineConfig({
  root: HERE,
  plugins: [react(), fixtureApi()],
});
