# Standalone SLURM Epilog Wipe Test

Reproduces the SLURM epilog wipe-while-running bug **without Nextflow**.

## The Bug

SLURM's `10-epilog.sh` runs `rm -Rf /data/scratch/<jobid>` when a job completes,
but passes **multiple job IDs** — including jobs that are **still running**.
This deletes a running task's scratch directory out from under it.

## Array-job reproduction (confirmed on node055)

The exact Nextflow failure mode is reproduced by a single SLURM array job where
most tasks finish together while two tasks keep running.

```bash
sbatch run_array_probe.sh
```

See `ARRAY_PROBE_EVIDENCE.md` for the full evidence. Both runs reproduced it:
the epilog of the gang of short tasks ran one `rm -Rf` listing **all**
`/data/scratch/<numeric job id>` dirs on the node, including the two
still-`RUNNING` long tasks, whose stage-out then failed with exit 42.

Trigger: a *gang* of near-simultaneous completions. A lone finishing task only
removes its own scratch dir.

**Warning:** this also wipes scratch dirs of other running jobs on the target
node. Only run it on a node you may disrupt, or during a maintenance window.

## Wildcard variant (node055 / earth-1)

On `node055` / `earth-1` the epilog was observed running:

```bash
rm -Rf /data/scratch/*
```

That deletes the scratch dirs of **all** jobs on the node, including jobs that
are still `RUNNING`. It does not mention a job ID, so a probe must treat a
wildcard `/data/scratch/*` as touching its own scratch.

The two-job reproducer:

```bash
WILDCARD_PROBE_YES=1 ./submit_wildcard_probe.sh 55 earth-1 60
```

It submits:

1. a long-running probe on `node055`,
2. a short trigger job on the same node.

When the trigger job completes, its epilog runs the wildcard `rm`. The long
probe should log:

```text
EPILOG_RM own=True ... argv=rm -Rf /data/scratch/*
SCRATCH_WIPED = True
PARENT_WIPED = True
CONCRETE_EVIDENCE: caught epilog rm + scratch/marker wiped = wipe-while-running confirmed
```

**Warning:** this wipes `/data/scratch` on the target node, including other
users' running jobs. Only run it on a node you may disrupt, or during a
maintenance window.

## How to Run

```bash
# no reservation
./submit_probe.sh 13 100

# with a reservation (e.g. haep_50 on node020)
./submit_probe.sh 20 100 haep_50
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
