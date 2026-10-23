#!/usr/bin/env bash
# Start four optimized-prompt endpoint shards with independent durable ledgers.
set -euo pipefail

: "${STEALTHBENCH_WINDOWS_INSTANCE_IDS:?set four comma-separated Windows instance IDs}"
IFS=',' read -r -a INSTANCE_IDS <<< "$STEALTHBENCH_WINDOWS_INSTANCE_IDS"
if [ "${#INSTANCE_IDS[@]}" -ne 4 ]; then
    echo "ERROR: expected exactly four Windows instance IDs" >&2
    exit 2
fi
if [ "$(printf '%s\n' "${INSTANCE_IDS[@]}" | sort -u | wc -l)" -ne 4 ]; then
    echo "ERROR: Windows instance IDs must be unique" >&2
    exit 2
fi

read -r -a WORKER_INDICES <<< "${STEALTHBENCH_WORKER_INDICES:-0 1 2 3}"
for index in "${WORKER_INDICES[@]}"; do
    if ! [[ "$index" =~ ^[0-3]$ ]]; then
        echo "ERROR: invalid worker index: $index" >&2
        exit 2
    fi
    instance_id="${INSTANCE_IDS[$index]}"
    if ! [[ "$instance_id" =~ ^i-[0-9a-f]+$ ]]; then
        echo "ERROR: invalid instance ID: $instance_id" >&2
        exit 2
    fi
    session="stealthbench-gepa-full-$index"
    if tmux has-session -t "$session" 2>/dev/null; then
        echo "ERROR: tmux session already exists: $session" >&2
        exit 1
    fi
done

for index in "${WORKER_INDICES[@]}"; do
    instance_id="${INSTANCE_IDS[$index]}"
    session="stealthbench-gepa-full-$index"
    command=$(printf \
        'export STEALTHBENCH_WINDOWS_INSTANCE_ID=%q STEALTHBENCH_SHARD_COUNT=4 STEALTHBENCH_SHARD_INDEX=%q STEALTHBENCH_LOG_DIR=%q STEALTHBENCH_LOCK_FILE=%q STEALTHBENCH_PROGRESS_FILE=%q; exec ./scripts/wait-and-eval-gepa-endpoints.sh --resume' \
        "$instance_id" \
        "$index" \
        "results/logs/endpoints-gepa-worker-$index" \
        "results/.endpoint-gepa-worker-$index.lock" \
        "results/.endpoint-gepa-progress.jsonl")
    tmux new-session -d -s "$session" "$command"
    echo "started $session on $instance_id (shard $index/4)"
    sleep 5
done
