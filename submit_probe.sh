#!/bin/bash
# submit_probe.sh — submit N standalone epilog probes to SLURM
# Usage: ./submit_probe.sh [node_number] [count] [reservation]
# Example: ./submit_probe.sh 13 30
#          ./submit_probe.sh 20 100 haep_50
#          ./submit_probe.sh 20 100 none

NODE="${1:-13}"
COUNT="${2:-30}"
RESERVATION="${3:-none}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Submitting ${COUNT} standalone epilog probes to node0${NODE}..."
echo "Spacing: 1s between submissions (matching Nextflow behavior)"

RESERVE_ARGS=""
if [ "${RESERVATION}" != "none" ]; then
    RESERVE_ARGS="--reservation=${RESERVATION}"
    echo "Using reservation: ${RESERVATION}"
fi

for i in $(seq 1 "${COUNT}"); do
    echo "  [${i}/${COUNT}] submitting..."
    sbatch --partition=earth-3 --time=00:05:00 --cpus-per-task=1 --mem=1G \
           --nodes=1 -w "node0${NODE}" ${RESERVE_ARGS} \
           -o "${SCRIPT_DIR}/slurm-%A_%a.out" -e "${SCRIPT_DIR}/slurm-%A_%a.err" \
           "${SCRIPT_DIR}/run_probe.sh"
    sleep 1
done

echo "Done."
