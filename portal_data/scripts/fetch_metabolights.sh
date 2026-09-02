#!/bin/sh
set -eu

# Usage:
#   ./fetch_metabolights.sh [TARGETS_FILE] [DEST_ROOT]
#
# Mirrors the MetaboLights study directories listed in TARGETS_FILE (as
# produced by search_euPMC_rest_API.py) from the EBI FTP server into
# DEST_ROOT, using lftp for resumable mirroring.
#
#   TARGETS_FILE  Lines of "FLAG REMOTE_PATH [LOCAL_PATH]". LOCAL_PATH, if
#                 present, is ignored -- DEST_ROOT below always decides
#                 where studies land. Defaults to targets.txt next to this
#                 script.
#   DEST_ROOT     Local directory to mirror studies into. Defaults to a
#                 "datasets" directory next to this script (so it can be
#                 .gitignored and the script can be run from anywhere).

BASE_HOST="ftp.ebi.ac.uk"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGETS_FILE="${1:-$SCRIPT_DIR/targets.txt}"
DEST_ROOT="${2:-$SCRIPT_DIR/datasets}"

echo "Using targets file: $TARGETS_FILE"
echo "Destination root:   $DEST_ROOT"
echo

# fields: FLAG REMOTE_PATH LOCAL_PATH
while read -r flag remote_path local_path; do
  # Skip empty lines or comments
  [ -z "${remote_path:-}" ] && continue
  case "$remote_path" in
    \#*) continue ;;
  esac

  study_dir=$(basename "$remote_path")
  study_dir=${study_dir%/}  # strip trailing slash

  echo "=== Mirroring $study_dir ==="
  echo "  Remote: ftp://${BASE_HOST}${remote_path}"
  echo "  Local:  ${DEST_ROOT}/${study_dir}/"

  # -c: continue (resume)
  # --verbose: show what it's doing
  # remote path: $remote_path
  # local path:  $DEST_ROOT/$study_dir
  lftp -c "
    set ftp:ssl-allow no;
    open ${BASE_HOST};
    mirror -c --verbose \"${remote_path}\" \"${DEST_ROOT}/${study_dir}\";
  "

  echo
done < "$TARGETS_FILE"

echo "All mirrors attempted."
