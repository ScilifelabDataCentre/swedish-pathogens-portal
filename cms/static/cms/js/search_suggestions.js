(() => {
  const toggle = document.querySelector("[data-search-toggle]");
  const panel = document.querySelector("[data-search-panel]");
  if (!toggle || !panel) return; // Exit if the header search is not on this page

  const input = panel.querySelector("input[type='search']");
  const results = panel.querySelector("[data-search-suggest-panel]");
  const close = panel.querySelector("[data-search-close]");

  // Without this script the toggle stays a plain link to the search page.
  toggle.setAttribute("role", "button");
  toggle.setAttribute("aria-expanded", "false");

  const isOpen = () => !panel.hidden;

  const open = () => {
    panel.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
    toggle.classList.add("btn-active");
    input.focus();
  };

  // Focus goes back to the toggle unless the user moved it somewhere else
  // themselves, by clicking or tabbing out of the panel.
  const shut = ({ returnFocus = true } = {}) => {
    if (!isOpen()) return;
    panel.hidden = true;
    // Reopening starts clean: Escape clears the field in some browsers, and the
    // suggestions left behind would then answer a query that is no longer there.
    results.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    toggle.classList.remove("btn-active");
    if (returnFocus) toggle.focus();
  };

  toggle.addEventListener("click", (event) => {
    event.preventDefault();
    if (isOpen()) shut();
    else open();
  });

  // A link only reacts to Enter; with role="button" it must react to Space too.
  toggle.addEventListener("keydown", (event) => {
    if (event.key !== " ") return;
    event.preventDefault();
    toggle.click();
  });

  close.addEventListener("click", () => shut());

  panel.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    // Stop the page-level handler from also closing the mobile menu.
    event.stopPropagation();
    shut();
  });

  // Tabbing past the panel closes it, so it does not hang over the page.
  // relatedTarget is null when the window itself loses focus: leave it open then.
  panel.addEventListener("focusout", (event) => {
    const next = event.relatedTarget;
    if (next && !panel.contains(next) && next !== toggle) shut({ returnFocus: false });
  });

  // pointerdown rather than click, so the panel is gone before the press lands.
  document.addEventListener("pointerdown", (event) => {
    if (panel.contains(event.target) || toggle.contains(event.target)) return;
    shut({ returnFocus: false });
  });

  // The mobile menu covers the header; close the panel rather than leave it under it.
  document.getElementById("mobile-menu-button")?.addEventListener("click", () => {
    shut({ returnFocus: false });
  });

  // Reveal before the swap, not after: the list is an aria-live region, and a
  // region that is still hidden when its content changes is not announced.
  results.addEventListener("htmx:beforeSwap", () => {
    results.hidden = false;
  });
  results.addEventListener("htmx:afterSwap", () => {
    // A cleared field returns an empty partial: collapse rather than leave a gap.
    if (results.innerHTML.trim() === "") results.hidden = true;
  });
})();
