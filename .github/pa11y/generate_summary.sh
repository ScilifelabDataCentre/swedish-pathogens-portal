#!/usr/bin/env bash

set -euo pipefail

RESULTS_FILE="${1:-pa11y-results.json}"

# --------------------------------------------------
# Check that the results file exists
# --------------------------------------------------

if [[ ! -f "$RESULTS_FILE" ]]; then
    echo "⚠️ Could not find \`$RESULTS_FILE\`."
    exit 0
fi

# --------------------------------------------------
# Validate the expected Pa11y JSON structure
# --------------------------------------------------

if ! jq -e '
    type == "object"
    and (.total | type == "number")
    and (.passes | type == "number")
    and (.errors | type == "number")
    and (.results | type == "object")
' "$RESULTS_FILE" > /dev/null 2>&1; then
    echo "⚠️ Could not find expected keys, check if Pa11y changed JSON output."
    exit 0
fi

# --------------------------------------------------
# Extract summary information
# --------------------------------------------------

TOTAL_PAGES=$(jq '.total' "$RESULTS_FILE")
PAGES_PASSED=$(jq '.passes' "$RESULTS_FILE")
PAGES_FAILED=$((TOTAL_PAGES - PAGES_PASSED))

# --------------------------------------------------
# Summary
# --------------------------------------------------

echo "| Metric | Count |"
echo "|---|---:|"
echo "| Total pages | ${TOTAL_PAGES} |"
echo "| Pages passed | ${PAGES_PASSED} |"
echo "| Pages failed | ${PAGES_FAILED} |"
echo

# --------------------------------------------------
# Failed pages and their errors
# --------------------------------------------------

if [[ "$PAGES_FAILED" -eq 0 ]]; then
    echo "## ✅ All pages passed"
    exit 0
fi

echo "### ❌ Pages with accessibility issues"
echo

jq -r '
    .results
    | to_entries[]
    | select(.value | length > 0)
    |
    "#### \(.key)\n"
    + (
        .value
        | map(
            "- **Code:** \(.code)\n"
            + "  **Message:** \(.message)\n"
            + "  **Selector:** `\(.selector)`\n"
            + "  **Context:** `\(.context)`\n"
          )
        | join("\n")
      )
    + "\n"
' "$RESULTS_FILE"
