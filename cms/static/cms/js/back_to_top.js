(() => {
  const btn = document.querySelector(".back-to-top");  // Get the button element
  if (!btn) return; // Exit if button is not found

  const SHOW_AFTER_PX = 350; // Show button after scrolling down

  // Function to toggle visibility
  const setVisibility = () => { 
    const show = window.scrollY > SHOW_AFTER_PX;

    // Toggle to show the button
    btn.classList.toggle("visible", show);
    btn.classList.toggle("opacity-100", show);
    btn.classList.toggle("translate-y-0", show);

    // Toggle to hide the button
    btn.classList.toggle("invisible", !show);
    btn.classList.toggle("opacity-0", !show);
    btn.classList.toggle("translate-y-2", !show);
  };

  setVisibility(); // Initial run - in case page is loaded scrolled down
  window.addEventListener("scroll", setVisibility, { passive: true });  // Run on scroll, passive for performance
})();
