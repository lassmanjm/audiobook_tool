#! /bin/bash

DIR=$(dirname "$0")
ENV_DIR="$DIR/ab_tool_env"
echo $ENV_DIR
if [ -d "$ENV_DIR" ]; then
  echo "Virtual environment already exists! Updating requirements..."
else
  echo "Creating virtual environment..."
  python3 -m venv "$ENV_DIR"
fi

source "$ENV_DIR/bin/activate"
pip3 install -r "$DIR/requirements.txt"
deactivate
