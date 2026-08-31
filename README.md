# Standalone SLURM Epilog Wipe Test

Reproduces the SLURM epilog wipe-while-running bug **without Nextflow**.

## The Bug

SLURM's `10-epilog.sh` runs `rm -Rf /data/scratch/<jobid>` when a job completes,
but passes **multiple job IDs** — including jobs that are **still running**.
This deletes a running task's scratch directory out from under it.

## How to Run

```bash
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
