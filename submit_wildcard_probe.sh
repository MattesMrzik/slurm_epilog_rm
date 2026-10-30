#!/bin/bash
# submit_wildcard_probe.sh — reproduce the wildcard epilog wipe.
#
# On node055 / earth-1 the epilog runs:
#     rm -Rf /data/scratch/*
# which deletes the scratch dirs of jobs that are still running.
#
# This script submits:
#   1. one long-running probe job on the target node
#   2. one short trigger job on the same node
#
# When the short job completes, its epilog runs the wildcard rm. The long job
# should then report:
#   EPILOG_RM own=True ... argv=rm -Rf /data/scratch/*
#   SCRATCH_WIPED = True
#   PARENT_WIPED = True
#   CONCRETE_EVIDENCE: ...
#
# WARNING: running this will wipe /data/scratch on the target node, including
# scratch dirs of other users' running jobs. Only run it on a node you are
# allowed to disrupt, or during a maintenance window.
#
# Usage:
#   WILDCARD_PROBE_YES=1 ./submit_wildcard_probe.sh [node_number] [partition] [hold_seconds]
#
# Example:
#   WILDCARD_PROBE_YES=1 ./submit_wildcard_probe.sh 55 earth-1 60

NODE="${1:-55}"
PARTITION="${2:-earth-1}"
HOLD="${3:-60}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="node0${NODE}"

if [ "${WILDCARD_PROBE_YES:-0}" != "1" ]; then
    echo "Refusing to run: this reproduces 'rm -Rf /data/scratch/*' on ${HOST}."
    echo "It can delete scratch dirs of other running jobs on that node."
    echo "Re-run with: WILDCARD_PROBE_YES=1 $0 ${NODE} ${PARTITION} ${HOLD}"
    exit 1
fi

cd "${SCRIPT_DIR}" || exit 1

echo "Target: ${HOST} (${PARTITION}); long probe hold: ${HOLD}s"
echo "Submitting long-running probe..."

LONG=$(sbatch --parsable \
    --job-name=wildcard-long \
    --partition="${PARTITION}" \
    -w "${HOST}" \
    --time=00:10:00 \
    --cpus-per-task=1 \
    --mem=1G \
    -o "wildcard_long_%j.out" \
    -e "wildcard_long_%j.err" \
    --export=ALL,TRAP_HOLD_S="${HOLD}" \
    "${SCRIPT_DIR}/run_probe.sh")

if [ -z "${LONG}" ]; then
    echo "Failed to submit long probe" >&2
    exit 1
fi
echo "Long probe job: ${LONG}"

# Wait until the long probe is actually running on the target node.
for _ in $(seq 1 60); do
    STATE=$(squeue -h -j "${LONG}" -o '%T' 2>/dev/null)
    [ "${STATE}" = "RUNNING" ] && break
    sleep 1
done
STATE=$(squeue -h -j "${LONG}" -o '%T' 2>/dev/null)
if [ "${STATE}" != "RUNNING" ]; then
    echo "Long probe did not reach RUNNING (state=${STATE})" >&2
    scancel "${LONG}" 2>/dev/null || true
    exit 1
fi

echo "Long probe is RUNNING. Giving it 3s to create its marker..."
sleep 3

echo "Submitting short trigger job on the same node..."
SHORT=$(sbatch --parsable \
    --job-name=wildcard-trigger \
    --partition="${PARTITION}" \
    -w "${HOST}" \
    --time=00:02:00 \
    --cpus-per-task=1 \
    --mem=100M \
    --wrap 'sleep 2')

if [ -z "${SHORT}" ]; then
    echo "Failed to submit trigger job" >&2
    scancel "${LONG}" 2>/dev/null || true
    exit 1
fi
echo "Trigger job: ${SHORT}"

echo "Waiting for the long probe to finish..."
for _ in $(seq 1 $((HOLD + 90))); do
    STATE=$(squeue -h -j "${LONG}" -o '%T' 2>/dev/null)
    [ -z "${STATE}" ] && break
    sleep 1
done

if [ -n "$(squeue -h -j "${LONG}" -o '%T' 2>/dev/null)" ]; then
    echo "Long probe still running; cancelling it." >&2
    scancel "${LONG}" 2>/dev/null || true
fi

OUT="${SCRIPT_DIR}/wildcard_long_${LONG}.out"
echo
echo "===== ${OUT} ====="
if [ -f "${OUT}" ]; then
    cat "${OUT}"
else
    echo "(missing output file)"
fi

echo
echo "===== evidence ====="
if [ -f "${OUT}" ] && grep -q 'CONCRETE_EVIDENCE' "${OUT}"; then
    grep -E 'EPILOG_RM|SCRATCH_WIPED|PARENT_WIPED|CONCRETE_EVIDENCE|MARKER_WIPED|FOUND_OWN_CWD|scontrol output' "${OUT}"
    echo "RESULT: reproduced"
    exit 0
fi

echo "RESULT: not reproduced in this run"
exit 2
