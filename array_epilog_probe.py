#!/usr/bin/env python3
"""Array-task version of the epilog wipe probe.

Runs INSIDE one SLURM array task on a shared node.  It reproduces the scratch
layout used by Nextflow with `scratch = true`:

    TMPDIR=/data/scratch/<numeric task job id>
    cd $TMPDIR/nxf.XXXXXXXXXX          # created with mkdtemp, like nxf_mktemp

It drops a marker + some data files in that nxf.* dir, then polls, at high
frequency, whether the directory / marker / parent sentinel disappear *while
this task is still running*.  At the same time it watches /proc for the site
SLURM epilog (epilog -> 10-epilog.sh -> rm -Rf /data/scratch/...) and records
the literal argv when it sees a deletion that names our own scratch.

Everything is logged to PROBE_LOG_DIR on the shared filesystem (not to
$TMPDIR), so the evidence survives a scratch wipe.
"""

import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import time

MY_ID = os.environ.get("SLURM_JOB_ID", "")
ARRAY_ID = os.environ.get("SLURM_ARRAY_JOB_ID", "")
TASK_ID = os.environ.get("SLURM_ARRAY_TASK_ID", "")
HOLD_S = float(os.environ.get("HOLD_S", "5"))
LOG_DIR = os.environ["PROBE_LOG_DIR"]
SCTL = shutil.which("scontrol") or "/cm/shared/apps/slurm/current/bin/scontrol"

PARENT = os.environ.get("TMPDIR") or ("/data/scratch/" + MY_ID)
SCRATCH = tempfile.mkdtemp(prefix="nxf.", dir=PARENT)
os.chdir(SCRATCH)

LOG_PATH = os.path.join(LOG_DIR, "arrayprobe_%s_%s.log" % (ARRAY_ID, TASK_ID))
_log_fh = open(LOG_PATH, "a", buffering=1)

MARKER = os.path.join(SCRATCH, "PROBE_MARKER")
SENTINEL = os.path.join(PARENT, "PROBE_PARENT_SENTINEL")
WATCH = os.path.join(SCRATCH, "out.txt")

RM_COMMS = ("rm", "rmdir", "unlink", "mv", "find", "shred", "python", "python3")


def now():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg):
    line = "[%s] %s" % (now(), msg)
    print(line, flush=True)
    try:
        _log_fh.write(line + "\n")
    except Exception:
        pass


def read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except Exception:
        return ""


def cmdline(pid):
    return read("/proc/%d/cmdline" % pid).replace("\x00", " ").strip()


def comm(pid):
    return read("/proc/%d/comm" % pid).strip()


def stat(pid):
    data = read("/proc/%d/stat" % pid)
    end = data.rfind(")")
    if end < 0:
        return None, -1
    f = data[end + 2:].split()
    if len(f) < 2:
        return None, -1
    return f[0], int(f[1])


def children(pid):
    kids = set()
    try:
        for tid in os.listdir("/proc/%d/task" % pid):
            data = read("/proc/%d/task/%s/children" % (pid, tid))
            kids.update(int(x) for x in data.split())
    except Exception:
        pass
    return sorted(kids)


def walk(root, depth=8):
    info = {}
    frontier = [root]
    seen = {root}
    for _ in range(depth):
        nxt = []
        for p in frontier:
            st, pp = stat(p)
            if p not in info:
                info[p] = (comm(p), pp, cmdline(p))
            for c in children(p):
                if c in seen:
                    continue
                seen.add(c)
                stc, ppc = stat(c)
                info[c] = (comm(c), ppc, cmdline(c))
                nxt.append(c)
        if not nxt:
            break
        frontier = nxt
    return info


def ancestry(info, pid, depth=10):
    out = []
    cur = pid
    seen = set()
    for _ in range(depth):
        if not cur or cur in seen or cur not in info:
            break
        seen.add(cur)
        c, pp, argv = info[cur]
        out.append((cur, c, pp, argv))
        cur = pp
    return out


def state():
    blobs = 0
    try:
        blobs = sum(1 for n in os.listdir(SCRATCH) if n.startswith("blob_"))
    except Exception:
        pass
    return {
        "scratch": os.path.isdir(SCRATCH),
        "parent": os.path.isdir(PARENT),
        "marker": os.path.isfile(MARKER),
        "sentinel": os.path.isfile(SENTINEL),
        "blobs": blobs,
    }


def own_scratch_in(argv):
    """True if argv mentions our scratch dir / parent / job id."""
    for tok in argv.replace('"', " ").replace("'", " ").split():
        p = tok.rstrip("/")
        if p == SCRATCH or p.startswith(SCRATCH + "/"):
            return True
        if p == PARENT:
            return True
        if p in ("/data/scratch/" + MY_ID,):
            return True
    return False


def scontrol_state():
    # NOTE: the compute nodes ship an old Python 3.6, where subprocess.run()
    # has no capture_output/text kwargs.  Use Popen + communicate instead.
    try:
        proc = subprocess.Popen([SCTL, "show", "job", MY_ID],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        raw, _ = proc.communicate(timeout=5)
        out = raw.decode("utf-8", "replace")
        keep = []
        for line in out.splitlines():
            for key in ("JobId=", "JobState=", "NodeList=", "ArrayJobId=", "ArrayTaskId="):
                if key in line:
                    keep.append(line.strip())
                    break
        return " | ".join(keep)
    except Exception as exc:
        return "scontrol error: %r" % (exc,)


def create_inputs():
    with open(MARKER, "w") as fh:
        fh.write("created=%s job=%s array=%s task=%s scratch=%s\n" % (
            datetime.datetime.now().isoformat(), MY_ID, ARRAY_ID, TASK_ID, SCRATCH))
    with open(SENTINEL, "w") as fh:
        fh.write("job=%s task=%s pid=%d\n" % (MY_ID, TASK_ID, os.getpid()))
    with open(WATCH, "w") as fh:
        fh.write("hello from %s\n" % MY_ID)
    # Keep the epilog's rm busy long enough to be caught in /proc.  The long
    # task gets more data; short tasks stay small.
    nblobs = 64 if HOLD_S >= 15 else 8
    payload = os.urandom(1024 * 1024)
    for i in range(nblobs):
        with open(os.path.join(SCRATCH, "blob_%03d" % i), "wb") as fh:
            fh.write(payload)


def catch_epilog(seen):
    """If an epilog is alive, walk its tree fast and log any /data/scratch rm."""
    epilog_pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        c = comm(pid)
        if c in ("epilog", "10-epilog.sh"):
            epilog_pids.append(pid)
            continue
        cl = cmdline(pid)
        if "10-epilog.sh" in cl:
            epilog_pids.append(pid)
    if not epilog_pids:
        return
    log("SAW_EPILOG pids=%s" % epilog_pids)
    deadline = time.time() + 2.5
    while time.time() < deadline:
        for ep in epilog_pids:
            if not os.path.isdir("/proc/%d" % ep):
                continue
            info = walk(ep)
            for p, (c, ppid, argv) in info.items():
                if "/data/scratch" not in argv:
                    continue
                if c not in RM_COMMS and "10-epilog.sh" not in argv:
                    continue
                key = (p, argv)
                if key in seen:
                    continue
                seen.add(key)
                own = own_scratch_in(argv)
                log("EPILOG_RM own=%s pid=%d comm=%s argv=%s" % (own, p, c, argv))
                if own:
                    for row in ancestry(info, p):
                        log("  ANCESTRY pid=%d comm=%s ppid=%d argv=%s" % row)
                    log("  OWN_STATE_AT_RM %s" % scontrol_state())
                    log("  OWN_STATE_FS %s" % state())
        time.sleep(0.001)


def main():
    log("TASK_START job=%s array=%s task=%s host=%s" % (MY_ID, ARRAY_ID, TASK_ID, os.uname().nodename))
    log("PARENT=%s SCRATCH=%s TMPDIR=%s HOLD_S=%s" % (PARENT, SCRATCH, os.environ.get("TMPDIR"), HOLD_S))
    log("SUBMIT_DIR=%s" % os.environ.get("SLURM_SUBMIT_DIR", ""))
    log("STATE_AFTER_SETUP %s" % state())

    create_inputs()
    log("MARKER_CREATED path=%s exists=%s" % (MARKER, os.path.isfile(MARKER)))
    log("SENTINEL_CREATED path=%s exists=%s" % (SENTINEL, os.path.isfile(SENTINEL)))
    log("INPUT_FILES %s" % state())

    seen = set()
    wiped = None
    last_heartbeat = 0.0
    start = time.time()
    while time.time() - start < HOLD_S:
        st = state()
        if wiped is None and (not st["scratch"] or not st["marker"] or not st["parent"] or not st["sentinel"]):
            wiped = (time.time() - start, st)
            log("WIPE_DETECTED elapsed=%.3fs state=%s" % wiped)
            log("  OWN_STATE_AT_WIPE %s" % scontrol_state())
        if time.time() - last_heartbeat >= 1.0:
            last_heartbeat = time.time()
            log("HEARTBEAT elapsed=%.1fs state=%s" % (time.time() - start, st))
        catch_epilog(seen)
        time.sleep(0.01)

    # Last look, and a stage-out just like Nextflow does after the payload:
    # copy the marker + one output file back to the shared filesystem.
    final = state()
    log("LOOP_END elapsed=%.3fs state=%s" % (time.time() - start, final))
    stageout_ok = True
    try:
        shutil.copy2(MARKER, os.path.join(LOG_DIR, "stageout_marker_%s_%s.txt" % (ARRAY_ID, TASK_ID)))
        shutil.copy2(WATCH, os.path.join(LOG_DIR, "stageout_out_%s_%s.txt" % (ARRAY_ID, TASK_ID)))
        log("STAGE_OUT ok=1")
    except Exception as exc:
        stageout_ok = False
        log("STAGE_OUT ok=0 error=%r" % (exc,))

    if wiped is not None:
        log("VERDICT WIPED_WHILE_RUNNING elapsed=%.3fs at_state=%s" % (wiped[0], wiped[1]))
        log("VERDICT marker_exists_final=%s scratch_exists_final=%s parent_exists_final=%s"
            % (final["marker"], final["scratch"], final["parent"]))
        log("TASK_END job=%s task=%s exit=42" % (MY_ID, TASK_ID))
        sys.exit(42)
    if not stageout_ok:
        log("VERDICT SURVIVED_BUT_STAGE_OUT_FAILED")
        log("TASK_END job=%s task=%s exit=43" % (MY_ID, TASK_ID))
        sys.exit(43)
    log("VERDICT SURVIVED marker_exists=%s scratch_exists=%s parent_exists=%s"
        % (final["marker"], final["scratch"], final["parent"]))
    log("TASK_END job=%s task=%s exit=0" % (MY_ID, TASK_ID))
    sys.exit(0)


if __name__ == "__main__":
    main()
