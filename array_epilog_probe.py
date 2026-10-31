#!/usr/bin/env python3
"""Reproduce the SLURM epilog wiping a running task's scratch.

Runs inside one array task. It uses the per-task scratch dir directly:

    TMPDIR=/data/scratch/<numeric job id>

The epilog deletes that whole directory, so a nested nxf.* subdirectory is not
needed. The probe polls whether its marker/dir disappear while it is still
running and records the epilog's `rm -Rf /data/scratch/...` command from /proc.
"""

import datetime
import os
import shutil
import subprocess
import sys
import time

MY_ID = os.environ.get("SLURM_JOB_ID", "")
ARRAY_ID = os.environ.get("SLURM_ARRAY_JOB_ID", "")
TASK_ID = os.environ.get("SLURM_ARRAY_TASK_ID", "")
HOLD_S = float(os.environ.get("HOLD_S", "5"))
LOG_DIR = os.environ["PROBE_LOG_DIR"]
SCTL = shutil.which("scontrol") or "/cm/shared/apps/slurm/current/bin/scontrol"

PARENT = os.environ.get("TMPDIR") or ("/data/scratch/" + MY_ID)

LOG_PATH = os.path.join(LOG_DIR, "arrayprobe_%s_%s.log" % (ARRAY_ID, TASK_ID))
LOG_FH = open(LOG_PATH, "a", buffering=1)
MARKER = os.path.join(PARENT, "PROBE_MARKER")

DELETE_COMMS = ("rm", "rmdir", "unlink", "mv", "find", "shred", "python", "python3")


def now():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg):
    line = "[%s] %s" % (now(), msg)
    print(line, flush=True)
    try:
        LOG_FH.write(line + "\n")
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
    fields = data[end + 2:].split()
    if len(fields) < 2:
        return None, -1
    return fields[0], int(fields[1])


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
        for pid in frontier:
            state, ppid = stat(pid)
            info.setdefault(pid, (comm(pid), ppid, cmdline(pid)))
            for child in children(pid):
                if child in seen:
                    continue
                seen.add(child)
                state, ppid = stat(child)
                info[child] = (comm(child), ppid, cmdline(child))
                nxt.append(child)
        if not nxt:
            break
        frontier = nxt
    return info


def ancestry(info, pid, depth=10):
    out = []
    seen = set()
    for _ in range(depth):
        if not pid or pid in seen or pid not in info:
            break
        seen.add(pid)
        c, ppid, argv = info[pid]
        out.append((pid, c, ppid, argv))
        pid = ppid
    return out


def state():
    return {
        "dir": os.path.isdir(PARENT),
        "marker": os.path.isfile(MARKER),
    }


def own_scratch(argv):
    for token in argv.replace('"', " ").replace("'", " ").split():
        path = token.rstrip("/")
        if path == PARENT or path.startswith(PARENT + "/"):
            return True
        if path == "/data/scratch/" + MY_ID:
            return True
        if "/data/scratch/" in path and "*" in path:
            return True
    return False


def scontrol_state():
    try:
        proc = subprocess.Popen(
            [SCTL, "show", "job", MY_ID],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        raw, _ = proc.communicate(timeout=5)
        lines = []
        for line in raw.decode("utf-8", "replace").splitlines():
            if any(key in line for key in ("JobId=", "JobState=", "NodeList=", "ArrayJobId=", "ArrayTaskId=")):
                lines.append(line.strip())
        return " | ".join(lines)
    except Exception as exc:
        return "scontrol error: %r" % (exc,)


def create_inputs():
    with open(MARKER, "w") as fh:
        fh.write("job=%s array=%s task=%s scratch=%s\n" % (MY_ID, ARRAY_ID, TASK_ID, PARENT))


def catch_epilog(seen_rm, seen_epilog):
    epilogs = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        c = comm(pid)
        cl = cmdline(pid)
        if c in ("epilog", "10-epilog.sh") or "10-epilog.sh" in cl:
            epilogs.append(pid)
            if pid not in seen_epilog:
                seen_epilog.add(pid)
                log("SAW_EPILOG pid=%d comm=%s argv=%s" % (pid, c, cl))

    if not epilogs:
        return

    deadline = time.time() + 2.5
    while time.time() < deadline:
        for epilog in epilogs:
            if not os.path.isdir("/proc/%d" % epilog):
                continue
            info = walk(epilog)
            for pid, (c, ppid, argv) in info.items():
                if "/data/scratch" not in argv:
                    continue
                if c not in DELETE_COMMS and "10-epilog.sh" not in argv:
                    continue
                key = (pid, argv)
                if key in seen_rm:
                    continue
                seen_rm.add(key)
                own = own_scratch(argv)
                log("EPILOG_RM own=%s pid=%d comm=%s argv=%s" % (own, pid, c, argv))
                if own:
                    for row in ancestry(info, pid):
                        log("  ANCESTRY pid=%d comm=%s ppid=%d argv=%s" % row)
                    log("  OWN_STATE_AT_RM %s" % scontrol_state())
                    log("  OWN_STATE_FS %s" % state())
        time.sleep(0.001)


def main():
    log("TASK_START job=%s array=%s task=%s host=%s" % (MY_ID, ARRAY_ID, TASK_ID, os.uname().nodename))
    log("PARENT=%s TMPDIR=%s HOLD_S=%s" % (PARENT, os.environ.get("TMPDIR"), HOLD_S))

    create_inputs()
    log("INPUT_FILES %s" % state())

    seen_rm = set()
    seen_epilog = set()
    wiped = None
    start = time.time()

    while time.time() - start < HOLD_S:
        st = state()
        if wiped is None and (not st["dir"] or not st["marker"]):
            wiped = (time.time() - start, st)
            log("WIPE_DETECTED elapsed=%.3fs state=%s" % wiped)
            log("  OWN_STATE_AT_WIPE %s" % scontrol_state())
        catch_epilog(seen_rm, seen_epilog)
        time.sleep(0.01)

    final = state()
    log("LOOP_END elapsed=%.3fs state=%s" % (time.time() - start, final))

    if wiped is not None:
        log("VERDICT WIPED_WHILE_RUNNING elapsed=%.3fs at_state=%s" % wiped)
        log("TASK_END job=%s task=%s exit=42" % (MY_ID, TASK_ID))
        return 42

    log("VERDICT SURVIVED state=%s" % final)
    log("TASK_END job=%s task=%s exit=0" % (MY_ID, TASK_ID))
    return 0


if __name__ == "__main__":
    sys.exit(main())
