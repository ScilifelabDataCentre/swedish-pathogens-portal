/**
 * Genomic data page (ena_data block) — client-side behaviour for the ENA listing.
 *
 * Responsibilities:
 * - Mark #ena-listing as busy while HTMX swaps it, for screen readers
 * - Column chooser: hide table columns, remembered per data type in localStorage
 * - Record selection and the download dialog, kept per data type in localStorage
 * - "Show more" toggles for long facet lists
 *
 * Expects the markup from cms/blocks/ena_data.html and the listing partial
 * (cms/pages/genomic_data/partials/ena_listing.html). Everything is re-applied
 * after each HTMX swap of #ena-listing.
 */
// Mark the listing as busy while HTMX swaps it, so screen readers announce the new content once.
document.body.addEventListener("htmx:beforeRequest", (event) => {
    if (event.detail.target && event.detail.target.id === "ena-listing") {
        event.detail.target.setAttribute("aria-busy", "true");
    }
});
document.body.addEventListener("htmx:afterSettle", (event) => {
    if (event.detail.target && event.detail.target.id === "ena-listing") {
        event.detail.target.setAttribute("aria-busy", "false");
    }
});

// Column chooser: hides table columns in the browser, remembered per data type in
// localStorage, and re-applied after every HTMX swap of the listing.
(function () {
    const storageKey = (dataType) => "genomicData:hiddenColumns:" + dataType;

    function currentDataType() {
        const table = document.querySelector("#ena-listing table[data-data-type]");
        return table ? table.dataset.dataType : null;
    }

    function loadHidden(dataType) {
        try {
            return new Set(JSON.parse(localStorage.getItem(storageKey(dataType)) || "[]"));
        } catch (err) {
            return new Set();
        }
    }

    function saveHidden(dataType, hidden) {
        try {
            localStorage.setItem(storageKey(dataType), JSON.stringify([...hidden]));
        } catch (err) {
            // localStorage unavailable (private browsing, quota, etc.) - the choice just won't persist
        }
    }

    function applyHidden() {
        const dataType = currentDataType();
        if (!dataType) return;
        const hidden = loadHidden(dataType);
        // Only the table's cells: the column checkboxes carry data-col too, and must stay visible.
        document.querySelectorAll("#ena-listing th[data-col], #ena-listing td[data-col]").forEach((cell) => {
            cell.classList.toggle("hidden", hidden.has(cell.dataset.col));
        });
        document.querySelectorAll("#ena-listing .column-toggle").forEach((toggle) => {
            toggle.checked = !hidden.has(toggle.dataset.col);
        });
    }

    document.addEventListener("change", (event) => {
        const toggle = event.target.closest("#ena-listing .column-toggle");
        if (!toggle) return;
        const dataType = currentDataType();
        if (!dataType) return;
        const hidden = loadHidden(dataType);
        if (toggle.checked) {
            hidden.delete(toggle.dataset.col);
        } else {
            hidden.add(toggle.dataset.col);
        }
        saveHidden(dataType, hidden);
        applyHidden();
    });

    document.body.addEventListener("htmx:afterSettle", (event) => {
        if (event.detail.target && event.detail.target.id === "ena-listing") applyHidden();
    });
})();

// Record selection and the download dialog. The selection is kept in localStorage
// per data type, so it survives searching, filtering, sorting and paging, and is
// re-applied to the rendered checkboxes after every HTMX swap of the listing.
(function () {
    const storageKey = (dataType) => "genomicData:selected:" + dataType;

    function currentDataType() {
        const table = document.querySelector("#ena-listing table[data-data-type]");
        return table ? table.dataset.dataType : null;
    }

    function loadSelected(dataType) {
        try {
            return new Set(JSON.parse(localStorage.getItem(storageKey(dataType)) || "[]"));
        } catch (err) {
            return new Set();
        }
    }

    function saveSelected(dataType, selected) {
        try {
            localStorage.setItem(storageKey(dataType), JSON.stringify([...selected]));
        } catch (err) {
            // localStorage unavailable (private browsing, quota, etc.) - the selection just won't persist
        }
    }

    function rowCheckboxes() {
        return [...document.querySelectorAll("#ena-listing .ena-select")];
    }

    function refresh() {
        const dataType = currentDataType();
        if (!dataType) return;
        const selected = loadSelected(dataType);
        const rows = rowCheckboxes();
        rows.forEach((checkbox) => {
            checkbox.checked = selected.has(checkbox.dataset.acc);
        });
        const pageCheckbox = document.getElementById("ena-select-page");
        if (pageCheckbox) {
            const ticked = rows.filter((checkbox) => checkbox.checked).length;
            pageCheckbox.checked = rows.length > 0 && ticked === rows.length;
            pageCheckbox.indeterminate = ticked > 0 && ticked < rows.length;
        }
        document.querySelectorAll("#ena-listing .ena-selected-count").forEach((el) => {
            el.textContent = selected.size.toLocaleString("en-GB");
        });
        const clearButton = document.getElementById("ena-clear-selection");
        if (clearButton) clearButton.disabled = selected.size === 0;
    }

    document.addEventListener("change", (event) => {
        const dataType = currentDataType();
        if (!dataType) return;
        const target = event.target;
        if (target.matches("#ena-listing .ena-select")) {
            const selected = loadSelected(dataType);
            if (target.checked) {
                selected.add(target.dataset.acc);
            } else {
                selected.delete(target.dataset.acc);
            }
            saveSelected(dataType, selected);
            refresh();
        } else if (target.id === "ena-select-page") {
            const selected = loadSelected(dataType);
            rowCheckboxes().forEach((checkbox) => {
                if (target.checked) {
                    selected.add(checkbox.dataset.acc);
                } else {
                    selected.delete(checkbox.dataset.acc);
                }
            });
            saveSelected(dataType, selected);
            refresh();
        }
    });

    document.addEventListener("click", (event) => {
        const dataType = currentDataType();
        const dialog = document.getElementById("ena-download-dialog");
        if (event.target.closest("#ena-clear-selection") && dataType) {
            saveSelected(dataType, new Set());
            refresh();
        } else if (event.target.closest("#ena-open-download") && dialog && dataType) {
            // Offer "Selected records" only when there is a selection, and pick it by default then.
            const hasSelection = loadSelected(dataType).size > 0;
            const selectedScope = document.getElementById("ena-scope-selected");
            selectedScope.disabled = !hasSelection;
            (hasSelection ? selectedScope : document.getElementById("ena-scope-all")).checked = true;
            refresh();
            dialog.showModal();
        } else if (event.target.closest("#ena-download-dialog [data-close-dialog]") && dialog) {
            dialog.close();
        }
    });

    // The dialog's Download button submits the download form: send the current view
    // (from the address bar, which HTMX keeps up to date) and, if chosen, the selection.
    document.getElementById("ena-download-form").addEventListener("submit", (event) => {
        const form = event.target;
        const dataType = currentDataType();
        const scope = document.querySelector('#ena-download-dialog input[name="scope"]:checked');
        if (!dataType || !scope) {
            event.preventDefault();
            return;
        }
        const selected = [...loadSelected(dataType)];
        if (scope.value === "selected" && selected.length === 0) {
            event.preventDefault();
            return;
        }
        document.getElementById("ena-download-ids").value =
            scope.value === "selected" ? selected.join(",") : "";
        form.action = form.dataset.action + window.location.search;
        document.getElementById("ena-download-dialog").close();
    });

    document.body.addEventListener("htmx:afterSettle", (event) => {
        if (event.detail.target && event.detail.target.id === "ena-listing") refresh();
    });
})();

// Facet "Show more / Show less", as on the Portal data page. Delegated from the
// document, so it keeps working after HTMX swaps the listing.
document.addEventListener("click", (event) => {
    const button = event.target.closest("#ena-listing .facet-toggle");
    if (!button) return;
    const target = document.getElementById(button.dataset.target);
    if (!target) return;
    const isExpanded = button.getAttribute("aria-expanded") === "true";
    target.classList.toggle("hidden", isExpanded);
    button.setAttribute("aria-expanded", String(!isExpanded));
    button.textContent = isExpanded ? button.dataset.collapsedText : button.dataset.expandedText;
});
