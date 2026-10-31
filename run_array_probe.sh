#!/bin/bash
#SBATCH --job-name=arrwipe
#SBATCH --partition=earth-1
#SBATCH --nodes=1
#SBATCH -w node055
#SBATCH --array=0-13
#SBATCH --time=00:03:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=200M
#SBATCH -o arrayrun-%A_%a.out
#SBATCH -e arrayrun-%A_%a.err

# Array-job probe for the SLURM epilog wipe-while-running bug.
#
# 14 array tasks all start together on one node.  Two of them (0 and 7) run for
# 25 s; the other twelve finish after 3-5 s.  Every task runs directly in its own
# $TMPDIR and checks, while it is still alive, whether that dir is deleted when
# the short siblings finish and their epilogs run.
#
# TMPDIR is set by the site task prolog to /data/scratch/<numeric SLURM_JOB_ID>,
# i.e. a per-task node-local scratch dir.  Each array element gets its own
# numeric SLURM_JOB_ID, so each task has its own TMPDIR.  The epilog removes
# this whole per-task dir; no nested nxf.* subdirectory is needed.

SCRIPT_DIR="${SLURM_SUBMIT_DIR}"
LOG_DIR="${SCRIPT_DIR}/arrayprobe_logs_${SLURM_ARRAY_JOB_ID}"
mkdir -p "${LOG_DIR}"

TASK="${SLURM_ARRAY_TASK_ID}"
if [ "${TASK}" = "0" ] || [ "${TASK}" = "7" ]; then
    HOLD_S=25
else
    HOLD_S=$((3 + TASK % 3))
fi

export HOLD_S
export PROBE_LOG_DIR="${LOG_DIR}"

echo "=== array epilog probe: array=${SLURM_ARRAY_JOB_ID} task=${TASK} job=${SLURM_JOB_ID} node=$(hostname) hold=${HOLD_S}s ==="
exec python3 "${SCRIPT_DIR}/array_epilog_probe.py"
