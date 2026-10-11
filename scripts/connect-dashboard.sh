#!/bin/sh
# Run on the computer with your browser, using its existing SSH host/alias.
set -eu
if [ "$#" -lt 1 ] || [ "$#" -gt 3 ]; then
    echo "Usage: $0 SSH_HOST_OR_ALIAS [LOCAL_PORT=8765] [REMOTE_PORT=8765]" >&2
    exit 2
fi
dashboard_target=$1
dashboard_local_port=${2:-8765}
dashboard_remote_port=${3:-8765}
case "$dashboard_target" in -*|'') echo "Invalid SSH target" >&2; exit 2;; esac
case "$dashboard_local_port:$dashboard_remote_port" in *[!0-9:]*|:*|*:) echo "Ports must be numbers" >&2; exit 2;; esac
if [ "$dashboard_local_port" -lt 1 ] || [ "$dashboard_local_port" -gt 65535 ] || [ "$dashboard_remote_port" -lt 1 ] || [ "$dashboard_remote_port" -gt 65535 ]; then
    echo "Ports must be between 1 and 65535" >&2
    exit 2
fi
printf 'Open http://127.0.0.1:%s in your browser after the dashboard starts. Ctrl+C stops it.\n' "$dashboard_local_port"
exec ssh -tt -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o "RemoteCommand=cd /home/maksym/dev/apartment_crawler && exec sh scripts/dashboard.sh --port $dashboard_remote_port" \
    -L "127.0.0.1:$dashboard_local_port:127.0.0.1:$dashboard_remote_port" "$dashboard_target"
