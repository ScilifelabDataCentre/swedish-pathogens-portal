/**
 * HepaGeNIE dashboard — client-side behaviour for the TLN plot.
 *
 * Responsibilities:
 * - DE threshold / Plot change → full HTML plot swap (hover + colourbar rebuild)
 * - Enable CSV export links after a successful upload or example load
 * - Fit plot height to the equal-height upload/plot cards
 *
 * Expects #liver-dashboard with data-recompute-url, and a Plotly figure in
 * #liver-tln-plot.
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
    const plotMetricSelect = document.getElementById("liver-plot-metric-select");
    const validationErrors = document.getElementById("liver-validation-errors");

    function getPlotWrapper() {
        return document.getElementById("liver-tln-plot");
    }

    function getPlotGraphDiv() {
        const wrapper = getPlotWrapper();
        return wrapper ? wrapper.querySelector(".plotly-graph-div") : null;
    }

    /**
     * Grow/shrink the Plotly figure so the plot card matches the sidebar
     * height without leaving an empty strip under the chart.
     */
    function fitPlotToEqualCardHeight() {
        const plotCard = document.getElementById("tln-container");
        const wrapper = getPlotWrapper();
        const graph = getPlotGraphDiv();
        if (!plotCard || !wrapper || !graph || typeof Plotly === "undefined") {
            return;
        }

        const body = plotCard.querySelector(".card-body");
        const legend = document.getElementById("liver-colour-legend");
        const stats =
            document.getElementById("liver-analysis-stats") ||
            document.querySelector("#liver-tln-result > p");
        if (!body) {
            return;
        }

        let available = body.clientHeight;
        if (legend) {
            available -= legend.offsetHeight;
        }
        if (stats) {
            available -= stats.offsetHeight;
        }
        // Small gap allowance between plot and legend/stats.
        available -= 16;
        available = Math.max(Math.round(available), 480);

        wrapper.style.height = `${available}px`;
        wrapper.style.minHeight = `${available}px`;
        Plotly.relayout(graph, { height: available, autosize: true });
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

    function getCurrentPlotMetric() {
        if (plotMetricSelect) {
            return plotMetricSelect.value;
        }
        const wrapper = getPlotWrapper();
        return wrapper?.dataset.plotMetric || "difference";
    }

    function controlQuery() {
        return (
            `adj_p=${encodeURIComponent(getCurrentAdjP())}` +
            `&logfc_fold=${encodeURIComponent(getCurrentLogfcFold())}` +
            `&plot_metric=${encodeURIComponent(getCurrentPlotMetric())}`
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
    }

    function recomputeWithHtmlSwap() {
        if (!hasActiveSession() || !recomputeUrl || typeof htmx === "undefined") {
            return;
        }
        htmx.ajax("GET", `${recomputeUrl}?${controlQuery()}`, {
            target: "#liver-tln-panel",
            swap: "innerHTML",
            headers: {
                Accept: "text/html",
            },
        });
    }

    function handlePlotPanelSettled() {
        setHasSession(true);
        clearValidationErrors();
        enableExportLinks();
        requestAnimationFrame(() => fitPlotToEqualCardHeight());
    }

    adjPSelect?.addEventListener("change", () => recomputeWithHtmlSwap());
    logfcFoldSelect?.addEventListener("change", () => recomputeWithHtmlSwap());
    plotMetricSelect?.addEventListener("change", () => recomputeWithHtmlSwap());

    document.body.addEventListener("htmx:afterSettle", (event) => {
        if (event.detail.target?.id === "liver-tln-panel") {
            handlePlotPanelSettled();
        }
    });

    window.addEventListener("resize", () => {
        requestAnimationFrame(() => fitPlotToEqualCardHeight());
    });

    // Initial layout after Plotly paints the base figure.
    requestAnimationFrame(() => {
        requestAnimationFrame(() => fitPlotToEqualCardHeight());
    });
})();
