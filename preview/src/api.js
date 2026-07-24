// Data layer: fetch the page index, infobox templates and raw wikitext from the
// launcher (the STU-646 Python server in production, the Vite fixture
// middleware in dev). Same routes either way.

export async function fetchIndex() {
  const res = await fetch('/api/index.json');
  if (!res.ok) throw new Error(`index: ${res.status}`);
  return res.json();
}

export async function fetchTemplates() {
  const res = await fetch('/api/templates.json');
  if (!res.ok) throw new Error(`templates: ${res.status}`);
  return res.json();
}

export async function fetchPage(path) {
  const res = await fetch(`/api/page?path=${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(`page ${path}: ${res.status}`);
  return res.text();
}
