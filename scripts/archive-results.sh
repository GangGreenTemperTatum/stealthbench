#!/bin/bash
# Archive current results into a timestamped directory.
# Preserves prior smoke test data before the full eval sweep.
#
# Usage:
#   ./scripts/archive-results.sh              # archive with auto-generated tag
#   ./scripts/archive-results.sh smoke-v2     # archive with custom tag
set -euo pipefail

TAG="${1:-smoke}"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
ARCHIVE_DIR="results/archive/${TAG}-${TIMESTAMP}"

if [ ! -d results ] || [ -z "$(ls -A results/ 2>/dev/null | grep -v archive)" ]; then
    echo "Nothing to archive — results/ is empty or contains only archives."
    exit 0
fi

mkdir -p "$ARCHIVE_DIR"

# Move everything except the archive directory itself
for item in results/*/; do
    dirname=$(basename "$item")
    [ "$dirname" = "archive" ] && continue
    mv "$item" "$ARCHIVE_DIR/"
    echo "  archived: $dirname"
done

echo ""
echo "Archived to: $ARCHIVE_DIR"
echo "Results directory is now clean for the full eval sweep."
echo ""
echo "To restore: mv ${ARCHIVE_DIR}/* results/"
