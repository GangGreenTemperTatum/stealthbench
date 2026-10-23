#!/bin/bash
# Wait for a short-lived AWS session with SSM access, then run all live verifiers
# and the resumable endpoint evaluation. The verifier gate precedes every paid run.
set -euo pipefail

run_python() {
    if [ -x .venv/bin/python ]; then
        .venv/bin/python "$@"
    else
        uv run python "$@"
    fi
}

WAIT_SEC="${STEALTHBENCH_ENDPOINT_WAIT_SEC:-30}"
ARGS=("$@")
if [[ " ${ARGS[*]} " != *" --resume "* ]]; then
    ARGS+=(--resume)
fi

while true; do
    while ! run_python scripts/check-endpoint-access.py; do
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] waiting for SSM-capable AWS credentials"
        sleep "$WAIT_SEC"
    done

    set +e
    ./scripts/eval-endpoints.sh "${ARGS[@]}"
    status=$?
    set -e

    case "$status" in
        0)
            exit 0
            ;;
        75)
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] AWS/API session expired; preserving progress and waiting for refreshed .env credentials"
            ;;
        *)
            exit "$status"
            ;;
    esac
done
