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
echo "================================"

# Mimic what Nextflow scratch=true does:
# 1. Set TMPDIR to /data/scratch/<jobid>
# 2. Create a subdirectory under it (like nxf_mktemp does)
# 3. cd into that subdirectory
SCRATCH_BASE="/data/scratch/${SLURM_JOB_ID}"
mkdir -p "${SCRATCH_BASE}"
export TMPDIR="${SCRATCH_BASE}"
NXF_SCRATCH="$(mktemp -d -t nxf.XXXXXXXXXX)"
cd "${NXF_SCRATCH}"

echo "SCRATCH_BASE=${SCRATCH_BASE}"
echo "NXF_SCRATCH=${NXF_SCRATCH}"
echo "PWD after cd=$(pwd)"

python3 "${SCRIPT_DIR}/epiltrap_standalone.py"
