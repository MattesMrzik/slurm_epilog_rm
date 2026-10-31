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
- each task uses `$TMPDIR/nxf.XXXXXXXXXX`, the same layout Nextflow uses with
  `scratch = true`.

When the short tasks finish together, the epilog runs one `rm -Rf` covering all
`/data/scratch/<numeric job id>` dirs on the node, including the two still-running
tasks. They detect the wipe while `JobState=RUNNING` and exit with code 42.

## Evidence

See `ARRAY_PROBE_EVIDENCE.md`. The key lines are:

```text
EPILOG_RM own=True pid=372822 comm=rm
  argv=rm -Rf /data/scratch/1079026 /data/scratch/1079027 ... /data/scratch/1079039
  ANCESTRY rm <- 10-epilog.sh <- /cm/local/apps/cmd/scripts/epilog

JobState=RUNNING
OWN_STATE_FS {'scratch': False, 'parent': False, 'marker': False, 'sentinel': False}
```

## Warning

This wipes `/data/scratch` on the target node, including other users' running
jobs. Only run it on a node you may disrupt, or during a maintenance window.

## Files

- `run_array_probe.sh` — sbatch wrapper
- `array_epilog_probe.py` — per-task probe
- `ARRAY_PROBE_EVIDENCE.md` — saved evidence
