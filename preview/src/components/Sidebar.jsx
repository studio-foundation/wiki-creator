import React from 'react';

// Grouping for the nav, in display order. Non-entity pages (Main_Page,
// Synopsis, collations, categories) fall under "Pages".
const GROUPS = [
  { type: 'PERSON', label: 'Characters' },
  { type: 'PLACE', label: 'Locations' },
  { type: 'ORG', label: 'Organizations' },
  { type: 'FACTION', label: 'Factions' },
  { type: 'EVENT', label: 'Events' },
  { type: null, label: 'Pages' },
];

export default function Sidebar({ pages, book, currentSlug }) {
  return (
    <nav className="wiki-sidebar" aria-label="Wiki navigation">
      <div className="wiki-sidebar-title">{book || 'Wiki'}</div>
      {GROUPS.map(({ type, label }) => {
        const inGroup = pages.filter((p) => p.entityType === type);
        if (!inGroup.length) return null;
        return (
          <section key={label} className="wiki-nav-group">
            <h2 className="wiki-nav-heading">{label}</h2>
            <ul>
              {inGroup.map((p) => (
                <li key={p.slug}>
                  <a href={`#/${p.slug}`} aria-current={p.slug === currentSlug ? 'page' : undefined}>
                    {p.title}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </nav>
  );
}
