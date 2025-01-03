#! /bin/bash
SCRIPT_PATH=$(readlink -f "$0")
DIR=$(dirname "$SCRIPT_PATH")
source "$DIR/ab_tool_env/bin/activate"

python3 "$DIR/audiobook_tool.py" "$@"

deactivate



