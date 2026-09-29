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

    # Ignore comments, empty lines and lines without the expected delimiter.
    /^#/ || NF == 0 || !index($0, FS) {
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

        # Normalize result into a grouping key.
        result_key = result
        sub(/^"/, "", result_key)

        # If it does not start with a numeric HTTP status code e.g. "404 Not Found"
        # then remove everything after the first colon
        # e.g. "Timeout: Connection timed out" becomes "Timeout"
        if (result_key !~ /^[0-9]+[[:space:]]/) {
            sub(/:.*/, "", result_key)
        }

        # Keep the order in which result groups first appear.
        if (!(result_key in result_seen)) {
            result_count++
            result_groups[result_count] = result_key
            result_seen[result_key] = 1
        } else {
            result_seen[result_key]++
        }

        # Keep the order in which parent URLs first appear
        # within each result group.
        group_parent_key = result_key SUBSEP parent

        if (!(group_parent_key in parent_seen)) {
            parent_count[result_key]++
            parents[result_key, parent_count[result_key]] = parent
            parent_seen[group_parent_key] = 1
        }

        # Store each failure under its result + parent.
        i = count[result_key, parent] + 1
        count[result_key, parent] = i

        names[result_key, parent, i]   = name
        urls[result_key, parent, i]    = url
        results[result_key, parent, i] = result

        total_broken_links++
    }

    END {
        if (result_count == 0) {
            print "### ✅ No broken links"
            exit 0
        }

        # Count unique pages across all result groups.
        for (r = 1; r <= result_count; r++) {
            result_key = result_groups[r]

            for (p = 1; p <= parent_count[result_key]; p++) {
                parent = parents[result_key, p]

                if (!(parent in all_parents_seen)) {
                    all_parents_count++
                    all_parents_seen[parent] = 1
                }
            }
        }

        print "⚠️ **Note that not all links listed below may be broken.**"
        print "*For example a 403 status code means the `linkchecker` was not allowed access to the website to check.*"
        print ""
        print "### Summary"
        print ""
        print "| Metric | Count |"
        print "|---|---:|"
        print "| Number of Pages with broken links | " all_parents_count " |"
        print "| Total number of broken links | " total_broken_links " |"

        # Stat for each result group.
        for (r = 1; r <= result_count; r++) {
            result_key = result_groups[r]
            print "| " result_key " | " result_seen[result_key] " |"
        }
        print ""

        for (r = 1; r <= result_count; r++) {
            result_key = result_groups[r]

            print "### ❌ " result_key
            print ""

            for (p = 1; p <= parent_count[result_key]; p++) {
                parent = parents[result_key, p]

                print "#### " parent
                print ""

                for (i = 1; i <= count[result_key, parent]; i++) {
                    print "  - **Link name:** `" names[result_key, parent, i] "`"
                    print "    **URL:** " urls[result_key, parent, i]
                    print "    **Result:** " results[result_key, parent, i]
                    print ""
                }
            }
        }
    }
' "$RESULTS_FILE"
