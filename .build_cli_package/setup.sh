#!/bin/bash
################################################################################
# VNStock CLI Installer - Setup Entry Point
#
# This script is called by the self-extracting .run installer
# It extracts files and runs the main Python installer
#
################################################################################

# Get script directory (where files are extracted)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run the main installer
python3 "$SCRIPT_DIR/vnstock_cli.py" "$@"
