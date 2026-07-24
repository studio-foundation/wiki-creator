import React, { useEffect, useState } from 'react';

import { fetchPage } from '../api.js';
import { renderWikitext } from '../wikitext/parse.js';

export default function Page({ page, templates }) {
  const [state, setState] = useState({ status: 'loading' });

  useEffect(() => {
    let alive = true;
    setState({ status: 'loading' });
    fetchPage(page.path)
      .then((wikitext) => {
        if (alive) setState({ status: 'ready', ...renderWikitext(wikitext, { templates }) });
      })
      .catch((e) => {
        if (alive) setState({ status: 'error', error: String(e) });
      });
    return () => {
      alive = false;
    };
  }, [page.path, templates]);

  if (state.status === 'loading') return <div className="state">Loading {page.title}…</div>;
  if (state.status === 'error') {
    return <div className="state state-error">Could not load {page.title}: {state.error}</div>;
  }

  return (
    <article className="wiki-page">
      <h1 className="wiki-page-title">{page.title}</h1>
      <div className="wiki-content" dangerouslySetInnerHTML={{ __html: state.html }} />
      {state.categories.length > 0 && (
        <footer className="wiki-categories">
          <span className="wiki-categories-label">Categories:</span>
          <ul>
            {state.categories.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </footer>
      )}
    </article>
  );
}
