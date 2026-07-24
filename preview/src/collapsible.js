// Make the parser's native mw-collapsible spoiler markup actually collapse
// (STU-649). The exporter emits `class="mw-collapsible mw-collapsed"` with
// data-expandtext / data-collapsetext; this wires a clickable toggle and the
// initial collapsed state. CSS (styles.css) hides the content when collapsed.

export function wireCollapsibles(root) {
  if (!root) return;
  for (const el of root.querySelectorAll('.mw-collapsible')) {
    if (el.dataset.wired) continue;
    el.dataset.wired = '1';

    const expandText = el.dataset.expandtext || 'Show';
    const collapseText = el.dataset.collapsetext || 'Hide';

    // Wrap the existing content so it can be hidden as one unit — a bare text
    // node (an inline gated infobox value like "Alive") can't be hidden by CSS
    // otherwise. Inline spans get a span wrapper, block divs a div wrapper.
    const content = document.createElement(el.tagName === 'SPAN' ? 'span' : 'div');
    content.className = 'wiki-collapsible-content';
    while (el.firstChild) content.appendChild(el.firstChild);
    el.appendChild(content);

    const toggle = document.createElement('span');
    toggle.className = 'wiki-collapsible-toggle';
    toggle.setAttribute('role', 'button');
    toggle.setAttribute('tabindex', '0');

    const apply = (collapsed) => {
      el.classList.toggle('is-collapsed', collapsed);
      toggle.classList.toggle('is-open', !collapsed);
      toggle.textContent = collapsed ? expandText : collapseText;
      toggle.setAttribute('aria-expanded', String(!collapsed));
    };
    const flip = () => apply(!el.classList.contains('is-collapsed'));

    toggle.addEventListener('click', flip);
    toggle.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        flip();
      }
    });

    el.insertBefore(toggle, content);
    apply(el.classList.contains('mw-collapsed'));
  }
}
