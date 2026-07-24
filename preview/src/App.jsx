import React, { useEffect, useState } from 'react';

import { fetchIndex, fetchTemplates } from './api.js';
import Sidebar from './components/Sidebar.jsx';
import Page from './components/Page.jsx';

/** Current route = the page slug after `#/` (e.g. "characters/Alice"), or "" for
 * the landing page. Kept in the URL hash so links and reloads work with no
 * router dependency. */
function useHashRoute() {
  const read = () => decodeURIComponent(window.location.hash.replace(/^#\/?/, ''));
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onHash = () => setRoute(read());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  return route;
}

export default function App() {
  const [index, setIndex] = useState(null);
  const [templates, setTemplates] = useState({});
  const [error, setError] = useState(null);
  const route = useHashRoute();

  useEffect(() => {
    Promise.all([fetchIndex(), fetchTemplates()])
      .then(([idx, tpl]) => {
        setIndex(idx);
        setTemplates(tpl);
      })
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <div className="state state-error">Failed to load the wiki: {error}</div>;
  if (!index) return <div className="state">Loading…</div>;
  if (!index.pages.length) {
    return <div className="state state-empty">No pages found — run the pipeline for this book first.</div>;
  }

  const landing = index.pages.find((p) => p.path === 'Main_Page.wiki') || index.pages[0];
  const current = index.pages.find((p) => p.slug === route) || landing;

  return (
    <div className="wiki-layout">
      <Sidebar pages={index.pages} book={index.book} currentSlug={current.slug} />
      <main className="wiki-main">
        <Page page={current} templates={templates} />
      </main>
    </div>
  );
}
