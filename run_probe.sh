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
# Just create a subdirectory inside it (like nxf_mktemp does) and cd into it.
NXF_SCRATCH="$(mktemp -d -t nxf.XXXXXXXXXX)"
cd "${NXF_SCRATCH}"

echo "NXF_SCRATCH=${NXF_SCRATCH}"
echo "PWD after cd=$(pwd)"

python3 "${SCRIPT_DIR}/epiltrap_standalone.py"
