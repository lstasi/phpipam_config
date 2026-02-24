#!/usr/bin/env bash
#
# sync_all.sh - Sync all configured OPNsense servers
#
# This script loops through all directories in sync_configs/ and runs
# the sync for each one that has a .env file.
#

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SYNC_WRAPPER="$SCRIPT_DIR/sync_wrapper.sh"
SYNC_CONFIGS_DIR="$PROJECT_ROOT/sync_configs"

# Check if sync_configs directory exists
if [ ! -d "$SYNC_CONFIGS_DIR" ]; then
    echo "Error: sync_configs directory not found: $SYNC_CONFIGS_DIR" >&2
    exit 1
fi

# Counter for statistics
TOTAL=0
SUCCESS=0
FAILED=0

echo "=========================================="
echo "Syncing all OPNsense configurations"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
echo ""

# Loop through all directories in sync_configs
for config_dir in "$SYNC_CONFIGS_DIR"/*/; do
    # Skip if not a directory
    [ -d "$config_dir" ] || continue

    # Skip if no .env file
    [ -f "$config_dir/.env" ] || continue

    CONFIG_NAME="$(basename "$config_dir")"
    TOTAL=$((TOTAL + 1))

    echo "[$TOTAL] Syncing: $CONFIG_NAME"

    if "$SYNC_WRAPPER" "$config_dir"; then
        echo "    ✓ Success"
        SUCCESS=$((SUCCESS + 1))
    else
        echo "    ✗ Failed (exit code: $?)"
        FAILED=$((FAILED + 1))
    fi
    echo ""
done

# Summary
echo "=========================================="
echo "Sync Summary"
echo "=========================================="
echo "Total configurations: $TOTAL"
echo "Successful: $SUCCESS"
echo "Failed: $FAILED"
echo "Completed: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# Exit with error if any failed
if [ $FAILED -gt 0 ]; then
    exit 1
fi

exit 0
