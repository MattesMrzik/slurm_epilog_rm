# Standalone SLURM Epilog Wipe Test

Reproduces the SLURM epilog wipe-while-running bug **without Nextflow**.

## The Bug

SLURM's `10-epilog.sh` runs `rm -Rf /data/scratch/<jobid>` when a job completes,
but passes **multiple job IDs** — including jobs that are **still running**.
This deletes a running task's scratch directory out from under it.

## How to Run

```bash
cd /cfs/earth/scratch/mrzi/develop/tkf_eval/cleanup_tests/standalone_epilog_test

# Submit 100 jobs to node013
./submit_probe.sh 13 100
```

## What to Look For

1. Check `sacct` for failed jobs (exit code 1 = caught the wipe):
   ```bash
   sacct --format=JobID,State,ExitCode,Elapsed,NodeList -u $USER -S $(date -d '10 minutes ago' +%Y-%m-%d:%H:%M)
   ```

2. Look at `.out` files containing `CONCRETE_EVIDENCE`:
   ```bash
   grep -l CONCRETE_EVIDENCE slurm-*.out
   ```

3. In those files you'll see:
   - `FOUND_OWN_CWD = (/data/scratch/<jobid>/nxf.XXXXX) in child of epilog: rm -Rf /data/scratch/<id1> /data/scratch/<id2> /data/scratch/<id3>`
   - `MARKER_CHECK_FINAL exists=False`
   - `CONCRETE_EVIDENCE: caught epilog rm + marker wiped = wipe-while-running confirmed`
   - `scontrol` output showing the job was `RUNNING` at the moment of the wipe

## Why Nextflow was needed before

The original reproduction used Nextflow with `scratch=true` because that sets:
- `TMPDIR=/data/scratch/<jobid>`
- Creates a subdirectory `nxf.XXXXXXXXXX` under it
- `cd`s into that subdirectory

This matches what `run_probe.sh` now does manually, eliminating Nextflow as a variable.

## Key Findings

- The epilog (`10-epilog.sh`) wipes scratch for **3 job IDs at a time**, not just the completed one
- Jobs pinned to the same node with 1s spacing overlap enough for the epilog to fire mid-run
- The wipe happens within ~2-4 seconds of job start
