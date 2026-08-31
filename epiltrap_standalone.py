#!/usr/bin/env python3
# epiltrap_standalone.py — standalone version that creates a marker at the
# start and checks whether the SLURM epilog wiped it by the end.
#
# Expects to be launched from inside /data/scratch/<jobid>/nxf.XXXXXXXXXX
# (matching what Nextflow scratch=true does via run_probe.sh).

import os, sys, time, datetime, subprocess

MY_ID    = os.environ.get("SLURM_JOB_ID", "job id not found")
HOLD_S   = float(os.environ.get("TRAP_HOLD_S", "4"))

RM_COMMS = ("rm", "rmdir", "unlink", "mv", "find", "python", "rmtree")

SCTL = "/cm/shared/apps/slurm/current/bin/scontrol"

def comm_of(pid):
    try:
        return open("/proc/%d/comm" % pid, "rb").read().decode("utf-8", "replace").strip()
    except Exception:
        return ""

def cmdline_of(pid):
    try:
        b = open("/proc/%d/cmdline" % pid, "rb").read(4096)
        return b.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except Exception:
        return ""

def stat_of(pid):
    try:
        b = open("/proc/%d/stat" % pid, "rb").read(256).decode("utf-8", "replace")
        end = b.rfind(")")
        rest = b[end+2:].split()
        if len(rest) >= 2:
            return rest[0], rest[1]  # (state, ppid)
    except Exception:
        pass
    return None

def children_of(pid):
    tids = []
    try:
        tids = [t for t in os.listdir("/proc/%d/task" % pid)]
    except Exception:
        return []
    kids = set()
    for t in tids:
        try:
            c = open("/proc/%d/task/%s/children" % (pid, t), "rb").read(4096).decode()
            kids.update(int(x) for x in c.split())
        except Exception:
            pass
    return sorted(kids)

def walk_descendants(root_pid, depth=8):
    st = stat_of(root_pid)
    ppid = int(st[1]) if st else -1
    info = {root_pid: (comm_of(root_pid), ppid, cmdline_of(root_pid))}
    frontier = [root_pid]
    seen = set([root_pid])
    for _ in range(depth):
        nxt = []
        for p in frontier:
            for c in children_of(p):
                if c in seen:
                    continue
                seen.add(c)
                stc = stat_of(c)
                info[c] = (comm_of(c), int(stc[1]) if stc else -1, cmdline_of(c))
                nxt.append(c)
        if not nxt:
            break
        frontier = nxt
    return info

def ancestry_chain(info, start_pid):
    chain = []
    cur = start_pid
    seen = set()
    for _ in range(12):
        if not cur or cur in seen:
            break
        seen.add(cur)
        a = info.get(cur)
        if a is None:
            break
        ccm, cpp, cargv = a
        chain.append((cur, ccm, cpp, cargv))
        cur = cpp
    return chain

def find_epilog():
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        pid = int(pid)
        if comm_of(pid) in ("epilog", "10-epilog.sh"):
            return pid, cmdline_of(pid)
    return None, None

def create_marker():
    """Create marker file in the current directory (already set up by run_probe.sh)."""
    cwd = os.getcwd()
    with open("PROBE_MARKER", "w") as f:
        f.write(f"created={datetime.datetime.now().isoformat()}\n")
        f.write(f"job_id={MY_ID}\n")
        f.write(f"pid={os.getpid()}\n")
        f.write(f"cwd={cwd}\n")
    print(f"MARKER_CREATED cwd={cwd} time={datetime.datetime.now().isoformat()}")

def check_marker():
    """Return (exists, content) for the marker file."""
    try:
        with open("PROBE_MARKER", "r") as f:
            content = f.read().strip()
        return True, content
    except FileNotFoundError:
        return False, ""
    except Exception as e:
        return False, f"ERROR: {e}"

def main():
    # ---- Phase 1: create marker ----
    create_marker()
    marker_exists_after_create, _ = check_marker()
    print(f"MARKER_CHECK_1 exists={marker_exists_after_create}")

    # write some filler files to keep busy (relative to cwd = SCRATCH)
    block = os.urandom(65536)
    mb = 64
    nfiles = max(1, int((mb * 1024 * 1024) / 65536))
    for i in range(nfiles):
        try:
            with open(f"blob_{i}", "wb") as f:
                f.write(block)
        except Exception:
            break

    # ---- Phase 2: scan for epilog ----
    start = time.time()
    caught = False
    while time.time() - start < HOLD_S:
        ep_pid, ep_argv = find_epilog()
        if ep_pid is None:
            time.sleep(0.002)
            continue

        print("Found epilog")
        window = time.time()
        while time.time() - window < 2.0:
            info = walk_descendants(ep_pid)
            for p, (comm, ppid, argv) in info.items():
                if comm not in RM_COMMS:
                    continue
                if "/data/scratch" not in argv and MY_ID not in argv:
                    continue
                if MY_ID in argv.replace("/data/scratch/", " ").split():
                    cwd = os.getcwd()
                    print(f"FOUND_OWN_CWD = ({cwd}) in child of epilog: {argv}")
                    print(f"Ancestry_chain = {ancestry_chain(info, ppid)}")
                    caught = True

                    # live job state
                    print("--- live job state ---")
                    output = os.popen(f'{SCTL} show job {MY_ID}').read()
                    print(f"scontrol output = {output}")
                    print("--- / end live job state ---")
                    break
            if caught:
                break
            time.sleep(0.001)
        if caught:
            break

    # ---- Phase 3: check marker ----
    # small pause so filesystem ops settle
    time.sleep(0.5)
    marker_exists_final, marker_content = check_marker()
    print(f"MARKER_CHECK_FINAL exists={marker_exists_final}")
    if marker_exists_final:
        print(f"MARKER_CONTENT = {marker_content}")
    else:
        print("MARKER_WIPED = True — epilog deleted our marker while we were still running!")

    # ---- Phase 4: summary ----
    print("=" * 60)
    exit_code = 0
    if caught and not marker_exists_final:
        print("CONCRETE_EVIDENCE: caught epilog rm + marker wiped = wipe-while-running confirmed")
        exit_code = 1
    elif caught and marker_exists_final:
        print("PARTIAL_EVIDENCE: caught epilog rm but marker survived")
    elif not caught and not marker_exists_final:
        print("MARKER_MISSING_BUT_NOT_CAUGHT: marker gone but epilog not observed live")
    else:
        print("NO_EVIDENCE: marker survived and epilog not observed")
    print("=" * 60)

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
