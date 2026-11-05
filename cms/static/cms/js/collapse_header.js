/* Function to make the header collapse while scrolling */

(() => {
    const header = document.querySelector("header");
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // when header is not found or if user have enabled reduced motion
    // setting then don't make the header collapse and keep it sticky
    if (!header || prefersReducedMotion) return; 

    // check if a menu is visible, used to check while collapsing header
    let isMenuOpen = false;

    const allMenus = document.querySelectorAll("header div[role='menu']");
    allMenus.forEach(menu => {
        menu.parentElement.addEventListener("mouseenter", () => {
            isMenuOpen = true;
        });
        menu.parentElement.addEventListener("mouseleave", () => {
            isMenuOpen = false;
        });
    });

    // the search panel hangs below the header, so it would slide away with it
    const searchPanel = header.querySelector("[data-search-panel]");
    const isSearchOpen = () => searchPanel && !searchPanel.hidden;

    const minimumScrollThreshold = 80;
    let lastScrollY = window.scrollY;

    // function to collapse or show the header
    const collapseHeader = () => {
        const currentScrollY = window.scrollY;

        // hide header only if any menu is NOT open and visible
        if (!isMenuOpen && !isSearchOpen()) {
            if (currentScrollY > lastScrollY && currentScrollY > minimumScrollThreshold) {
                // Scrolling down
                header.classList.add("-translate-y-[95%]", "shadow-lg");
                header.classList.remove("translate-y-0", "shadow-sm");
            } else {
                // Scrolling up
                header.classList.add("translate-y-0", "shadow-sm");
                header.classList.remove("-translate-y-[95%]", "shadow-lg");
            }
        }

        // save current value for next check
        lastScrollY = currentScrollY;
    };

    window.addEventListener("scroll", collapseHeader, { passive: true })
})()
