#!/usr/bin/env bash

set -euo pipefail

RESULTS_FILE="${1:-linkchecker-results.csv}"

# --------------------------------------------------
# Check that the results file exists
# --------------------------------------------------

if [[ ! -f "$RESULTS_FILE" ]]; then
    echo "⚠️ Could not find \`$RESULTS_FILE\`."
    exit 0
fi

# --------------------------------------------------
# Validate the expected LinkChecker CSV structure
# --------------------------------------------------

if ! awk '
    /^urlname\|/ {
        header = $0

        n = split(header, columns, "|")

        for (i = 1; i <= n; i++) {
            found[columns[i]] = 1
        }

        required["parentname"] = 1
        required["name"]       = 1
        required["urlname"]        = 1
        required["result"]     = 1

        for (column in required) {
            if (!found[column]) {
                missing = missing (missing ? ", " : "") column
            }
        }

        if (missing) {exit 2}

        found_header = 1
        exit 0
    }

    END {
        if (!found_header) {
            print "⚠️ Missing header(s): " missing > "/dev/stderr"
            exit 2
        }
    }
' "$RESULTS_FILE"; then
    echo "Could not find all expected LinkChecker CSV columns."
    echo "Expected columns: parentname, name, result, url"
    echo "Check the task out to know about run details."
    exit 0
fi

# --------------------------------------------------
# Generate summary
# --------------------------------------------------

awk '
    BEGIN {
        FS = "|"
    }

    # Ignore comments and empty lines.
    /^#/ || NF == 0 {
        next
    }

    # Find the actual CSV header.
    /^urlname\|/ {
        header = $0

        n = split(header, columns, "|")

        for (i = 1; i <= n; i++) {
            column[columns[i]] = i
        }

        next
    }

    {
        parent = $(column["parentname"])
        name   = $(column["name"])
        url    = $(column["urlname"])
        result = $(column["result"])

        # Keep the order in which parent URLs first appear.
        if (!(parent in seen)) {
            parent_count++
            parents[parent_count] = parent
            seen[parent] = 1
        }

        count[parent]++
        total_broken_links++

        # Store each failure under its parent.
        i = count[parent]

        names[parent, i]   = name
        urls[parent, i]    = url
        results[parent, i] = result
    }

    END {
        if (parent_count == 0) {
            print "### ✅ No broken links"
            exit 0
        }

        print "| Metric | Count |"
        print "|---|---:|"
        print "| Number of Pages with broken links | " parent_count " |"
        print "| Total number of broken links | " total_broken_links " |"
        print ""

        print "### ❌ Broken links"
        print ""

        for (p = 1; p <= parent_count; p++) {
            parent = parents[p]

            print "#### " parent
            print ""

            for (i = 1; i <= count[parent]; i++) {
                print "  - **Link name:** `" names[parent, i] "`"
                print "    **URL:** " urls[parent, i]
                print "    **Result:** " results[parent, i]
                print ""
            }
        }
    }
' "$RESULTS_FILE"
