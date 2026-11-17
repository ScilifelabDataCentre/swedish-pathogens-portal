/**
 * HepaGeNIE dashboard — client-side behaviour for the TLN plot.
 *
 * Responsibilities:
 * - DE threshold change → recompute colours (Plotly.restyle for solid leaves,
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
    const adjPSelect = document.getElementById("liver-adj-p-select");
    const logfcFoldSelect = document.getElementById("liver-logfc-fold-select");
    const validationErrors = document.getElementById("liver-validation-errors");

    function getPlotWrapper() {
        return document.getElementById("liver-tln-plot");
    }

    function getPlotGraphDiv() {
        const wrapper = getPlotWrapper();
        return wrapper ? wrapper.querySelector(".plotly-graph-div") : null;
    }

    function getCurrentAdjP() {
        if (adjPSelect) {
            return adjPSelect.value;
        }
        const wrapper = getPlotWrapper();
        return wrapper?.dataset.adjP || "0.05";
    }

    function getCurrentLogfcFold() {
        if (logfcFoldSelect) {
            return logfcFoldSelect.value;
        }
        const wrapper = getPlotWrapper();
        return wrapper?.dataset.logfcFold || "1.5";
    }

    function thresholdQuery() {
        return (
            `adj_p=${encodeURIComponent(getCurrentAdjP())}` +
            `&logfc_fold=${encodeURIComponent(getCurrentLogfcFold())}`
        );
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

        const thresholdLabel = stats.cutoff || "DE threshold";

        if (stats.plot_mode === "pie" && Array.isArray(stats.filenames)) {
            const comparisonSummary = stats.filenames
                .map((filename) => `<span class="inline-block mr-3">${filename}</span>`)
                .join("");
            statsEl.innerHTML =
                `<span class="font-medium">${stats.file_count} comparisons</span>` +
                ` · pie mode · DE threshold: ${thresholdLabel}` +
                `<span class="block mt-1 text-xs">${comparisonSummary}</span>`;
            return;
        }

        statsEl.innerHTML =
            `<span class="font-medium">${stats.filename}</span>` +
            ` · ${stats.gene_count.toLocaleString()} genes` +
            ` · ${stats.n_up} up / ${stats.n_down} down` +
            ` · DE threshold: ${thresholdLabel}`;
    }

    async function recomputeThresholds() {
        if (!hasActiveSession() || !recomputeUrl) {
            return;
        }

        if (getPlotMode() === "pie") {
            if (typeof htmx !== "undefined") {
                dashboard.classList.add("liver-recomputing");
                htmx.ajax("GET", `${recomputeUrl}?${thresholdQuery()}`, {
                    target: "#liver-tln-panel",
                    swap: "innerHTML",
                    headers: {
                        Accept: "text/html",
                    },
                }).finally(() => {
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
            const response = await fetch(`${recomputeUrl}?${thresholdQuery()}`, {
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                credentials: "same-origin",
            });

            if (!response.ok) {
                return;
            }

            const payload = await response.json();
            await Plotly.restyle(
                plotDiv,
                { "marker.color": [payload.colours_array] },
                [payload.leaf_trace_index],
            );

            if (payload.stats?.filename && payload.stats?.cutoff) {
                await Plotly.relayout(plotDiv, {
                    "title.text": `HepaGeNIE TLN — ${payload.stats.filename} (${payload.stats.cutoff})`,
                });
            }

            const wrapper = getPlotWrapper();
            if (wrapper && payload.stats) {
                if (payload.stats.threshold_key) {
                    wrapper.dataset.cutoff = payload.stats.threshold_key;
                }
                if (payload.stats.adj_p != null) {
                    wrapper.dataset.adjP = String(payload.stats.adj_p);
                }
                if (payload.stats.logfc_fold != null) {
                    wrapper.dataset.logfcFold = String(payload.stats.logfc_fold);
                }
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

    adjPSelect?.addEventListener("change", recomputeThresholds);
    logfcFoldSelect?.addEventListener("change", recomputeThresholds);

    document.body.addEventListener("htmx:afterSettle", (event) => {
        if (event.detail.target?.id === "liver-tln-panel") {
            handlePlotPanelSettled();
        }
    });
})();
