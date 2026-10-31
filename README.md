# SLURM epilog wipe test

Reproduces the site epilog deleting scratch dirs of jobs that are still
**RUNNING**.

## Reproduce

```bash
sbatch run_array_probe.sh
```

The script submits one array job on `node055`:

- 14 tasks, all started together,
- tasks 0 and 7 run for 25 s,
- the other 12 tasks run for 3-5 s,
- each task uses its own `$TMPDIR` directly; the epilog removes that whole
  per-task dir, so no nested `nxf.*` is needed,
- long tasks create `256 × 256 KiB` filler files. This keeps the epilog's `rm`
  alive long enough to capture its PID and full argv.

When the short tasks finish together, the epilog runs one `rm -Rf` covering all
`/data/scratch/<numeric job id>` dirs on the node, including the two still-running
tasks. They detect the wipe while `JobState=RUNNING` and exit with code 42.

## Evidence

See `ARRAY_PROBE_EVIDENCE.md`. A confirmed run (array `1079355`) captured the
deleting process:

```text
EPILOG_RM own=True pid=464713 comm=rm
  argv=rm -Rf /data/scratch/1079355 /data/scratch/1079356 ... /data/scratch/1079367

WIPE_DETECTED elapsed=4.092s state={'dir': False, 'marker': False, 'files': 0}
JobState=RUNNING
VERDICT WIPED_WHILE_RUNNING
```

## Warning

This wipes `/data/scratch` on the target node, including other users' running
jobs. Only run it on a node you may disrupt, or during a maintenance window.

## Files

- `run_array_probe.sh` — sbatch wrapper
- `array_epilog_probe.py` — per-task probe
- `ARRAY_PROBE_EVIDENCE.md` — saved evidence
