# Array-job epilog wipe probe — REPRODUCED

Node: `node055` (`earth-1`). Array job: `1079026` (run 2; run 1 reproduced
identically).

## PID capture with filler (array `1079355`)

Long tasks create `256 × 256 KiB` filler files. This keeps the epilog's `rm`
alive long enough to capture its PID and argv:

```text
12:49:27.151 EPILOG_RM own=True pid=464713 comm=rm
  argv=rm -Rf /data/scratch/1079355 /data/scratch/1079356 /data/scratch/1079357
       /data/scratch/1079358 /data/scratch/1079360 /data/scratch/1079361
       /data/scratch/1079363 /data/scratch/1079364 /data/scratch/1079366
       /data/scratch/1079367

12:49:27.147 WIPE_DETECTED elapsed=4.092s state={'dir': False, 'marker': False, 'files': 0}
12:49:27.189   OWN_STATE_AT_WIPE JobId=1079356 ... JobState=RUNNING ...
```

Tasks 0, 2, 5, 7, and 8 were still running when wiped; they exited 42.

No nested subdirectory is required; the epilog removes the whole
`/data/scratch/<jobid>` directory.

## Design

One real SLURM array job with 14 tasks, all on the same node:

- tasks 0 and 7 hold for 25 s,
- the other 12 tasks hold for 3-5 s,
- every task uses its own `$TMPDIR` directly and creates a marker there
  (the epilog removes the whole per-task parent either way),
- every task polls whether its scratch/marker disappears and watches `/proc`
  for `epilog -> 10-epilog.sh -> rm -Rf /data/scratch/...`.

No extra watcher jobs or helper processes.

## Evidence

All tasks started at `18:19:50`. Task 9 finished alone at 3 s; its epilog removed
only its own directory:

```text
18:19:53.970 EPILOG_RM own=False pid=372547 comm=rm
  argv=rm -Rf /data/scratch/1079036
```

The other 11 short tasks finished together at `18:19:56`. One epilog then removed
every scratch dir on the node:

```text
18:19:56.540 EPILOG_RM own=True pid=372822 comm=rm
  argv=rm -Rf /data/scratch/1079026 /data/scratch/1079027 /data/scratch/1079028
       /data/scratch/1079029 /data/scratch/1079030 /data/scratch/1079031
       /data/scratch/1079032 /data/scratch/1079033 /data/scratch/1079034
       /data/scratch/1079035 /data/scratch/1079037 /data/scratch/1079038
       /data/scratch/1079039
  ANCESTRY pid=372822 comm=rm           ppid=372615
  ANCESTRY pid=372615 comm=10-epilog.sh ppid=372587
  ANCESTRY pid=372587 comm=epilog        ppid=3665
```

`1079027` (task 0) and `1079034` (task 7) were still running:

```text
18:19:56.585 OWN_STATE_AT_RM
  JobId=1079027 ArrayJobId=1079026 ArrayTaskId=0 ... JobState=RUNNING ...

18:19:56.587 OWN_STATE_FS
  {'scratch': False, 'parent': False, 'marker': False, 'sentinel': False}
```

Task 0's heartbeat 0.1 s earlier still had all its files:

```text
18:19:56.426 HEARTBEAT elapsed=5.1s
  {'scratch': True, 'parent': True, 'marker': True, 'sentinel': True}
```

The long tasks stayed alive with deleted scratch and then failed stage-out:

```text
18:20:16.322 STAGE_OUT ok=0 error=FileNotFoundError(2, 'No such file or directory')
18:20:16.330 TASK_END job=1079027 task=0 exit=42
```

`sacct` for run 2:

```text
1079026_0  FAILED     42:0  00:00:26  18:19:50  18:20:16  node055
1079026_1  COMPLETED   0:0  00:00:06  18:19:50  18:19:56  node055
...
1079026_7  FAILED     42:0  00:00:28  18:19:50  18:20:18  node055
1079026_8  COMPLETED   0:0  00:00:06  18:19:50  18:19:56  node055
1079026_9  COMPLETED   0:0  00:00:03  18:19:50  18:19:53  node055
...
```

## Interpretation

The epilog does not restrict itself to the task that completed. When many array
elements finish together, `10-epilog.sh` issues one `rm -Rf` with all
`/data/scratch/<numeric job id>` dirs present on the node. Array elements have
distinct numeric `SLURM_JOB_ID`s, so this deletes live scratch dirs of sibling
tasks that are still `RUNNING`.

A lone finishing task only removes its own directory. The trigger is a gang of
near-simultaneous completions.
