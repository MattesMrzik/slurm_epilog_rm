#!/bin/bash
#SBATCH --partition=earth-3
#SBATCH --time=00:05:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --nodes=1
#SBATCH -o slurm-%A_%a.out
#SBATCH -e slurm-%A_%a.err

SCRIPT_DIR="${SLURM_SUBMIT_DIR}"

echo "=== Standalone epilog probe ==="
echo "Job ID: ${SLURM_JOB_ID}"
echo "Node: $(hostname)"
echo "Working dir: $(pwd)"
echo "Time: $(date -Iseconds)"
echo "TMPDIR=${TMPDIR}"
echo "================================"

# SLURM already sets TMPDIR=/data/scratch/<jobid> and creates it.
# Nextflow with `scratch = true` does NOT run directly in $TMPDIR: it
# creates $TMPDIR/nxf.XXXXXXXXXX (see nxf_mktemp in .command.run) and cd's
# into that subdirectory.  Mimic that layout so the probe exercises the same
# path that Nextflow tasks use.
NXF_SCRATCH="$(mktemp -d "${TMPDIR}/nxf.XXXXXXXXXX")" || {
    echo "ERROR: could not create scratch dir under ${TMPDIR}" >&2
    exit 1
}
cd "${NXF_SCRATCH}"

echo "NXF_SCRATCH=${NXF_SCRATCH}"
echo "PWD after cd=$(pwd)"

# When submitted as a SLURM array, give every element a different lifetime.
# Nextflow array tasks also finish at different times; staggering makes the
# epilog of an early element run while later elements are still alive, which
# is the situation that can expose cross-job scratch deletion.
if [ -n "${SLURM_ARRAY_TASK_ID:-}" ] && [ -z "${TRAP_HOLD_S:-}" ]; then
    export TRAP_HOLD_S=$((6 + 2 * SLURM_ARRAY_TASK_ID))
fi
echo "TRAP_HOLD_S=${TRAP_HOLD_S:-8}"

python3 "${SCRIPT_DIR}/epiltrap_standalone.py"
