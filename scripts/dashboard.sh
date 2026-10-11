#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export PYTHONPATH=src
exec python3 -m rent_dashboard "$@"
