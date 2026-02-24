#!/usr/bin/env bash
#
# sync_wrapper.sh - Wrapper script for OPNsense → phpIPAM sync
#
# Usage: ./scripts/sync_wrapper.sh <config_dir>
#
# This script:
# - Sources environment variables from <config_dir>/.env
# - Runs the sync script
# - Logs output to a file (default: /var/log/phpipam-sync/<config_name>.log)
#

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SYNC_SCRIPT="$SCRIPT_DIR/opnsense_phpipam_sync.py"

# Check if config directory is provided
if [ $# -eq 0 ]; then
    echo "Error: No configuration directory specified" >&2
    echo "Usage: $0 <config_dir>" >&2
    echo "" >&2
    echo "Examples:" >&2
    echo "  $0 sync_configs/opnsense1" >&2
    echo "  $0 /absolute/path/to/config" >&2
    exit 1
fi

CONFIG_DIR="$1"

# Convert to absolute path if relative
if [[ ! "$CONFIG_DIR" = /* ]]; then
    CONFIG_DIR="$PROJECT_ROOT/$CONFIG_DIR"
fi

# Check if config directory exists
if [ ! -d "$CONFIG_DIR" ]; then
    echo "Error: Configuration directory not found: $CONFIG_DIR" >&2
    exit 1
fi

# Check if .env file exists
ENV_FILE="$CONFIG_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env file not found: $ENV_FILE" >&2
    echo "Hint: Copy .env_sample to .env and configure it" >&2
    exit 1
fi

# Get configuration name from directory
CONFIG_NAME="$(basename "$CONFIG_DIR")"

# Determine log file location
# Default: /var/log/phpipam-sync/<config_name>.log
# Can be overridden by LOG_FILE in .env
DEFAULT_LOG_DIR="/var/log/phpipam-sync"
DEFAULT_LOG_FILE="$DEFAULT_LOG_DIR/$CONFIG_NAME.log"

# Source the environment file
set -a
source "$ENV_FILE"
set +a

# Use LOG_FILE from env if set, otherwise use default
LOG_FILE="${LOG_FILE:-$DEFAULT_LOG_FILE}"

# Create log directory if it doesn't exist
LOG_DIR="$(dirname "$LOG_FILE")"
if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR" 2>/dev/null || {
        echo "Warning: Cannot create log directory: $LOG_DIR" >&2
        echo "Falling back to stdout/stderr" >&2
        LOG_FILE="/dev/stdout"
    }
fi

# Log start time
{
    echo "=========================================="
    echo "Sync started: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Configuration: $CONFIG_NAME"
    echo "Config directory: $CONFIG_DIR"
    echo "=========================================="
    echo ""
} >> "$LOG_FILE" 2>&1

# Run the sync script
python3 "$SYNC_SCRIPT" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

# Log completion
{
    echo ""
    echo "=========================================="
    echo "Sync completed: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Exit code: $EXIT_CODE"
    echo "=========================================="
    echo ""
} >> "$LOG_FILE" 2>&1

exit $EXIT_CODE
