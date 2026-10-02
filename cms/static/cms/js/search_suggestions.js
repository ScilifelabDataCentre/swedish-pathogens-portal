(() => {
  const form = document.querySelector("[data-search-suggest]");
  if (!form) return; // Exit if the header search box is not on this page

  const input = form.querySelector("input[type='search']");
  const panel = form.querySelector("[data-search-suggest-panel]");
  if (!input || !panel) return;

  // Set by Escape only. Focus returns to the input afterwards, so without this
  // the focus handler would reopen the panel the user just dismissed. Typing
  // again clears it, as does leaving the search box altogether.
  let dismissed = false;

  const isEmpty = () => panel.innerHTML.trim() === "";
  const hasFocus = () => form.contains(document.activeElement);
  const hide = () => panel.setAttribute("hidden", "");
  const show = () => panel.removeAttribute("hidden");
  // A reply can land after the user has moved on: only ever open the panel
  // while they are still in the search box and have not dismissed it.
  const mayShow = () => !dismissed && hasFocus();

  // Reveal before the swap, not after: the panel is an aria-live region, and a
  // region that is still hidden when its content changes is not announced.
  panel.addEventListener("htmx:beforeSwap", () => {
    if (mayShow()) show();
  });
  panel.addEventListener("htmx:afterSwap", () => {
    // A cleared field returns an empty partial — collapse rather than leave a gap.
    if (isEmpty()) hide();
  });

  input.addEventListener("input", () => {
    dismissed = false;
  });

  // Returning to the field brings back suggestions that are still loaded.
  input.addEventListener("focus", () => {
    if (mayShow() && !isEmpty()) show();
  });

  // Tabbing out dismisses, but moving focus onto a suggestion inside the panel
  // must not — relatedTarget is the element focus is going to.
  form.addEventListener("focusout", (event) => {
    if (form.contains(event.relatedTarget)) return;
    dismissed = false; // leaving resets; coming back may show again
    hide();
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
    // Set before focusing: Escape can come from a suggestion link, and pulling
    // focus back to the input fires the focus handler synchronously.
    dismissed = true;
    input.focus();
    hide();
  });
})();
