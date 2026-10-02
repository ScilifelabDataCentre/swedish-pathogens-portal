(() => {
  const form = document.querySelector("[data-search-suggest]");
  if (!form) return; // Exit if the header search box is not on this page

  const input = form.querySelector("input[type='search']");
  const panel = form.querySelector("[data-search-suggest-panel]");
  if (!input || !panel) return;

  const isEmpty = () => panel.innerHTML.trim() === "";
  const hide = () => panel.setAttribute("hidden", "");
  const show = () => panel.removeAttribute("hidden");

  // Reveal before the swap, not after: the panel is an aria-live region, and a
  // region that is still hidden when its content changes is not announced.
  panel.addEventListener("htmx:beforeSwap", show);
  panel.addEventListener("htmx:afterSwap", () => {
    // A cleared field returns an empty partial — collapse rather than leave a gap.
    if (isEmpty()) hide();
  });

  // Returning to the field brings back suggestions that are still loaded.
  input.addEventListener("focus", () => {
    if (!isEmpty()) show();
  });

  // Tabbing out dismisses, but moving focus onto a suggestion inside the panel
  // must not — relatedTarget is the element focus is going to.
  form.addEventListener("focusout", (event) => {
    if (!form.contains(event.relatedTarget)) hide();
  });

  // pointerdown rather than click, so the panel is gone before the press
  // completes; presses inside the panel still reach their link.
  document.addEventListener("pointerdown", (event) => {
    if (!form.contains(event.target)) hide();
  });

  form.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || panel.hasAttribute("hidden")) return;
    // Stop the page-level handler from also closing the mobile menu.
    event.stopPropagation();
    hide();
    input.focus();
  });
})();
