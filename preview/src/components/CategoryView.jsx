import React from 'react';

// Lists the pages that declare a given category. Reached from a category
// wikilink or the per-page categories footer (STU-650). Membership comes from
// the index (each page carries its `categories`), so no page fetching.
export default function CategoryView({ name, pages }) {
  const members = pages.filter((p) => (p.categories || []).includes(name));
  return (
    <article className="wiki-page">
      <h1 className="wiki-page-title">Category: {name}</h1>
      {members.length ? (
        <ul className="wiki-category-members">
          {members.map((p) => (
            <li key={p.slug}>
              <a className="wikilink" href={`#/${p.slug}`}>
                {p.title}
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <p className="state">No pages in this category.</p>
      )}
    </article>
  );
}
