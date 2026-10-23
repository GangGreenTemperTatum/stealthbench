#!/usr/bin/env bash
# Preserve and resume a GEPA endpoint shard across temporary AWS/API failures.
set -euo pipefail

WAIT_SEC="${STEALTHBENCH_ENDPOINT_WAIT_SEC:-30}"
ARGS=("$@")
if [[ " ${ARGS[*]} " != *" --resume "* ]]; then
    ARGS+=(--resume)
fi

while true; do
    while ! .venv/bin/python scripts/check-endpoint-access.py; do
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] waiting for endpoint access"
        sleep "$WAIT_SEC"
    done

    set +e
    ./scripts/eval-endpoints-gepa.sh "${ARGS[@]}"
    status=$?
    set -e
    case "$status" in
        0) exit 0 ;;
        75)
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] temporary dependency failure; resuming"
            sleep "$WAIT_SEC"
            ;;
        *) exit "$status" ;;
    esac
done
