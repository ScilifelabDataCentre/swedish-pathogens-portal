/**
 * DINA Liver Resource dashboard — client-side behaviour for the TLN plot.
 *
 * Responsibilities:
 * - DEcutoff change → recompute colours (Plotly.restyle for solid leaves,
 *   full htmx plot swap for pie leaves when data-plot-mode="pie")
 * - Enable CSV export links after a successful upload or example load
 *
 * Expects #liver-dashboard with data-recompute-url, and a Plotly figure with
 * leaf trace index in #liver-tln-plot data attributes.
 */
(function () {
    "use strict";

    const dashboard = document.getElementById("liver-dashboard");
    if (!dashboard) {
        return;
    }

    const recomputeUrl = dashboard.dataset.recomputeUrl;
    const cutoffSelect = document.getElementById("liver-cutoff-select");
    const validationErrors = document.getElementById("liver-validation-errors");

    function getPlotWrapper() {
        return document.getElementById("liver-tln-plot");
    }

    function getPlotGraphDiv() {
        const wrapper = getPlotWrapper();
        return wrapper ? wrapper.querySelector(".plotly-graph-div") : null;
    }

    function getCurrentCutoff() {
        if (cutoffSelect) {
            return cutoffSelect.value;
        }
        const wrapper = getPlotWrapper();
        return wrapper?.dataset.cutoff || "standard";
    }

    function hasActiveSession() {
        return dashboard.dataset.hasSession === "true";
    }

    function setHasSession(active) {
        dashboard.dataset.hasSession = active ? "true" : "false";
    }

    function clearValidationErrors() {
        if (validationErrors) {
            validationErrors.innerHTML = "";
        }
    }

    function enableExportLinks() {
        document.querySelectorAll(".liver-export-link").forEach((link) => {
            link.classList.remove("btn-disabled", "pointer-events-none");
            link.removeAttribute("aria-disabled");
            link.removeAttribute("tabindex");
        });
        const exportHint = document.getElementById("liver-export-hint");
        if (exportHint) {
            exportHint.hidden = true;
        }
    }

    function getPlotMode() {
        const wrapper = getPlotWrapper();
        return wrapper?.dataset.plotMode || "solid";
    }

    function updateAnalysisStats(stats) {
        const statsEl = document.getElementById("liver-analysis-stats");
        if (!statsEl || !stats) {
            return;
        }

        if (stats.plot_mode === "pie" && Array.isArray(stats.filenames)) {
            const comparisonSummary = stats.filenames
                .map((filename) => `<span class="inline-block mr-3">${filename}</span>`)
                .join("");
            statsEl.innerHTML =
                `<span class="font-medium">${stats.file_count} comparisons</span>` +
                ` · pie mode · cutoff: ${stats.cutoff}` +
                `<span class="block mt-1 text-xs">${comparisonSummary}</span>`;
            return;
        }

        statsEl.innerHTML =
            `<span class="font-medium">${stats.filename}</span>` +
            ` · ${stats.gene_count.toLocaleString()} genes` +
            ` · ${stats.n_up} up / ${stats.n_down} down` +
            ` · cutoff: ${stats.cutoff}`;
    }

    async function recomputeCutoff() {
        if (!hasActiveSession() || !recomputeUrl) {
            return;
        }

        if (getPlotMode() === "pie") {
            if (typeof htmx !== "undefined") {
                dashboard.classList.add("liver-recomputing");
                htmx.ajax(
                    "GET",
                    `${recomputeUrl}?cutoff=${encodeURIComponent(getCurrentCutoff())}`,
                    {
                        target: "#liver-tln-panel",
                        swap: "innerHTML",
                        headers: {
                            Accept: "text/html",
                        },
                    },
                ).finally(() => {
                    dashboard.classList.remove("liver-recomputing");
                });
            }
            return;
        }

        const plotDiv = getPlotGraphDiv();
        if (!plotDiv || typeof Plotly === "undefined") {
            return;
        }

        dashboard.classList.add("liver-recomputing");
        try {
            const response = await fetch(
                `${recomputeUrl}?cutoff=${encodeURIComponent(getCurrentCutoff())}`,
                {
                    headers: {
                        Accept: "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    credentials: "same-origin",
                },
            );

            if (!response.ok) {
                return;
            }

            const payload = await response.json();
            await Plotly.restyle(
                plotDiv,
                { "marker.color": [payload.colours_array] },
                [payload.leaf_trace_index],
            );

            const wrapper = getPlotWrapper();
            if (wrapper && payload.stats?.cutoff) {
                wrapper.dataset.cutoff = payload.stats.cutoff;
            }
            updateAnalysisStats(payload.stats);
        } finally {
            dashboard.classList.remove("liver-recomputing");
        }
    }

    function handlePlotPanelSettled() {
        setHasSession(true);
        clearValidationErrors();
        enableExportLinks();
    }

    cutoffSelect?.addEventListener("change", recomputeCutoff);

    document.body.addEventListener("htmx:afterSettle", (event) => {
        if (event.detail.target?.id === "liver-tln-panel") {
            handlePlotPanelSettled();
        }
    });
})();
