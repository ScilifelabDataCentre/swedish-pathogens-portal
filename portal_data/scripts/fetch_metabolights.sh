#!/bin/sh
set -eu

# Usage:
#   ./fetch_metabolights.sh [-a|--all] [TARGETS_FILE] [DEST_ROOT]
#
# By default, fetches each MetaboLights study's investigation file
# (i_Investigation.txt) listed in TARGETS_FILE (as produced by
# search_euPMC_rest_API.py) from the EBI FTP server, using lftp for
# resumable downloads. Each study's file is saved into its own
# DEST_ROOT/<project_number>/ folder.
#
#   -a, --all     Download every file in each study's directory (a full
#                 recursive mirror) instead of just i_Investigation.txt.
#   TARGETS_FILE  One MetaboLights study remote path per line, as written by
#                 search_euPMC_rest_API.py. Defaults to targets.txt next to
#                 this script.
#   DEST_ROOT     Local directory to save studies into. Defaults to a
#                 "datasets" directory next to this script (so it can be
#                 .gitignored and the script can be run from anywhere).

BASE_HOST="ftp.ebi.ac.uk"
INVESTIGATION_FILE="i_Investigation.txt"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

ALL_FILES=false
while [ $# -gt 0 ]; do
  case "$1" in
    -a|--all)
      ALL_FILES=true
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [-a|--all] [TARGETS_FILE] [DEST_ROOT]" >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

TARGETS_FILE="${1:-$SCRIPT_DIR/targets.txt}"
DEST_ROOT="${2:-$SCRIPT_DIR/datasets}"

echo "Using targets file: $TARGETS_FILE"
echo "Destination root:   $DEST_ROOT"
if [ "$ALL_FILES" = true ]; then
  echo "Mode:                downloading all files per study (--all)"
else
  echo "Mode:                downloading $INVESTIGATION_FILE only"
fi
echo

# one remote study path per line
while read -r remote_path; do
  # Skip empty lines or comments
  [ -z "${remote_path:-}" ] && continue
  case "$remote_path" in
    \#*) continue ;;
  esac

  study_dir=$(basename "$remote_path")
  study_dir=${study_dir%/}  # strip trailing slash

  mkdir -p "${DEST_ROOT}/${study_dir}"

  if [ "$ALL_FILES" = true ]; then
    echo "=== Mirroring all files for $study_dir ==="
    echo "  Remote: ftp://${BASE_HOST}${remote_path}"
    echo "  Local:  ${DEST_ROOT}/${study_dir}/"

    # -c: continue (resume)
    lftp -c "
      set ftp:ssl-allow no;
      open ${BASE_HOST};
      mirror -c --verbose \"${remote_path}\" \"${DEST_ROOT}/${study_dir}\";
    "
  else
    remote_file="${remote_path%/}/${INVESTIGATION_FILE}"

    echo "=== Fetching $study_dir ==="
    echo "  Remote: ftp://${BASE_HOST}${remote_file}"
    echo "  Local:  ${DEST_ROOT}/${study_dir}/${INVESTIGATION_FILE}"

    # -c: continue (resume)
    lftp -c "
      set ftp:ssl-allow no;
      open ${BASE_HOST};
      get -c \"${remote_file}\" -o \"${DEST_ROOT}/${study_dir}/${INVESTIGATION_FILE}\";
    "
  fi

  echo
done < "$TARGETS_FILE"

if [ "$ALL_FILES" = true ]; then
  echo "All files fetched."
else
  echo "All investigation files fetched."
fi
