# Array-job epilog wipe probe — result: REPRODUCED

Date: 2026-10-30
Node: node055 (partition earth-1, 36 idle CPUs)
Repo: `/cfs/earth/scratch/mrzi/develop/nextflow_output/epilog_probe/slurm_epilog_rm`
No changes were made to the Nextflow pipeline and nothing was committed.

## Files added

| file | purpose |
|---|---|
| `run_array_probe.sh` | sbatch wrapper; one array job, 14 tasks, node055 |
| `array_epilog_probe.py` | per-task body: creates `$TMPDIR/nxf.XXXXXXXXXX`, marker, files, polls for deletion, captures the epilog `rm` argv from `/proc` |
| `arrayprobe_logs_1079012/` | logs of run 1 |
| `arrayprobe_logs_1079026/` | logs of run 2 |

## Probe design

* One real SLURM array job, `--array=0-13`, all 14 tasks on node055, started together.
* Tasks 0 and 7 hold for 25 s; the other 12 hold for `3 + task % 3` seconds (3-5 s).
* Every task:
  * `TMPDIR=/data/scratch/<numeric SLURM_JOB_ID>` (set by the site task prolog),
  * creates `$TMPDIR/nxf.XXXXXXXXXX` with `mkdtemp` (the path Nextflow uses with `scratch = true`),
  * writes `PROBE_MARKER`, `out.txt`, a parent sentinel and 8/64 x 1 MiB blobs,
  * polls every 10 ms whether the nxf dir / marker / parent sentinel disappeared,
  * watches `/proc` for `epilog -> 10-epilog.sh -> rm -Rf /data/scratch/...` and logs the literal argv,
  * logs `scontrol show job <numeric id>` state at the moment of the wipe,
  * logs to the repo (shared FS) so evidence survives the scratch wipe.
* No extra watcher jobs and no helper processes: all logic runs inside the array tasks.

## sbatch command

```bash
cd /cfs/earth/scratch/mrzi/develop/nextflow_output/epilog_probe/slurm_epilog_rm
sbatch run_array_probe.sh          # job 1079012 (run 1)
sbatch run_array_probe.sh          # job 1079026 (run 2)
```

## Evidence (run 2, array 1079026)

Task start: `18:19:51.246`, all 14 tasks started at `18:19:50`.

Task 9 (3 s hold) finished alone at `18:19:53`; its epilog removed only its own dir:

```
18:19:53.970 EPILOG_RM own=False pid=372547 comm=rm argv=rm -Rf /data/scratch/1079036
```

The other 11 short tasks finished together at `18:19:56`. Their epilogs started as a
gang and one of them deleted **every** scratch dir on the node, including both
still-running long tasks:

```
18:19:56.540 EPILOG_RM own=True pid=372822 comm=rm
  argv=rm -Rf /data/scratch/1079026 /data/scratch/1079027 /data/scratch/1079028
       /data/scratch/1079029 /data/scratch/1079030 /data/scratch/1079031
       /data/scratch/1079032 /data/scratch/1079033 /data/scratch/1079034
       /data/scratch/1079035 /data/scratch/1079037 /data/scratch/1079038
       /data/scratch/1079039

  ANCESTRY pid=372822 comm=rm          ppid=372615
  ANCESTRY pid=372615 comm=10-epilog.sh ppid=372587
  ANCESTRY pid=372587 comm=epilog        ppid=3665

18:19:56.585 OWN_STATE_AT_RM
  JobId=1079027 ArrayJobId=1079026 ArrayTaskId=0 ... JobState=RUNNING ...

18:19:56.587 OWN_STATE_FS
  {'scratch': False, 'parent': False, 'marker': False, 'sentinel': False, 'blobs': 0}
```

`1079027` is task 0 and `1079034` is task 7 — both were 25 s tasks, still RUNNING.
Task 0's heartbeat 0.1 s before the rm still had all 64 blobs and the marker:

```
18:19:56.426 HEARTBEAT elapsed=5.1s
  {'scratch': True, 'parent': True, 'marker': True, 'sentinel': True, 'blobs': 64}
```

Task 0 then stayed alive for the remaining ~19 s with a deleted scratch, and its
Nextflow-style stage-out failed:

```
18:20:16.322 STAGE_OUT ok=0 error=FileNotFoundError(2, 'No such file or directory')
18:20:16.325 VERDICT WIPED_WHILE_RUNNING elapsed=7.716s ...
18:20:16.330 TASK_END job=1079027 task=0 exit=42
```

sacct for run 2 (`sacct -j 1079026 --format=JobID%14,State,ExitCode,Elapsed,Start,End -P`):

```
1079026_0  FAILED     42:0  00:00:26  18:19:50  18:20:16  node055
1079026_1  COMPLETED   0:0  00:00:06  18:19:50  18:19:56  node055
...
1079026_7  FAILED     42:0  00:00:28  18:19:50  18:20:18  node055
1079026_8  COMPLETED   0:0  00:00:06  18:19:50  18:19:56  node055
1079026_9  COMPLETED   0:0  00:00:03  18:19:50  18:19:53  node055
1079026_10 COMPLETED   0:0  00:00:06  18:19:50  18:19:56  node055
...
```

Run 1 (array 1079012) behaved identically: both long tasks were wiped at
`18:19:03.458` by

```
rm -Rf /data/scratch/1079012 ... /data/scratch/1079013 ... /data/scratch/1079020 ...
```

and exited 42; the short tasks completed normally.

## Interpretation

* The site epilog (`/cm/local/apps/cmd/scripts/epilog -> 10-epilog.sh`) does not
  restrict itself to the completed task. When several array elements complete at
  nearly the same time it issues one `rm -Rf` with **all** `/data/scratch/<numeric
  job id>` directories present on the node.
* Array elements get a distinct numeric `SLURM_JOB_ID` and
  `TMPDIR=/data/scratch/<numeric id>`, so those paths are the live per-task scratch
  dirs. The rm therefore deletes scratch of sibling tasks that are still RUNNING.
* The trigger is a *gang* of near-simultaneous completions. A lone task finishing
  (e.g. task 9 at 3 s) only removes its own dir; when 11 tasks finish together the
  epilog removes all 13 dirs at once. This also explains why the earlier staggered
  6/8/.../28 s array run did not reproduce it.
* This matches the observed Nextflow failure: array 1078939 on node055 at
  `18:08:42`, where 10 of 12 elements went RUNNING -> COMPLETING while element 10
  (numeric job 1078952, scratch `/data/scratch/1078952/nxf.aQzJaYnXHF`) stayed
  RUNNING; its scratch was removed just before/while Nextflow performed stage-out,
  which then failed to find `msa.fasta`, `.command.out` and `.command.err`.
