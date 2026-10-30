#!/usr/bin/env python3
# epiltrap_standalone.py — standalone version that creates a marker at the
# start and checks whether the SLURM epilog wiped it by the end.
#
# Expects to be launched from inside /data/scratch/<jobid>/nxf.XXXXXXXXXX
# (matching what Nextflow scratch=true does via run_probe.sh).
#
# The probe also creates a sentinel in the PARENT (/data/scratch/<jobid>) so
# the log can distinguish "epilog removed the whole job scratch dir" from
# "something removed only the nxf.* subdirectory".

import os, sys, time, datetime

MY_ID    = os.environ.get("SLURM_JOB_ID", "job id not found")
# For a SLURM array task SLURM_JOB_ID is "<arrayid>_<taskid>"; TMPDIR and
# /data/scratch usually use only the base array id.  Check both.
MY_BASE  = MY_ID.split("_", 1)[0]
HOLD_S   = float(os.environ.get("TRAP_HOLD_S", "8"))

PARENT_DIR = os.environ.get("TMPDIR", os.path.dirname(os.getcwd()))
SCRATCH_DIR = os.getcwd()

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

def argv_touches_me(argv):
    """True if an epilog rm command mentions our job id / scratch path."""
    for tok in argv.replace('"', ' ').replace("'", " ").split():
        p = tok.rstrip("/")
        if p == PARENT_DIR or p == SCRATCH_DIR or p.startswith(PARENT_DIR + "/"):
            return True
        if p == "/data/scratch/" + MY_BASE or p == "/data/scratch/" + MY_ID:
            return True
        # Wildcard epilog: rm -Rf /data/scratch/* touches every job.
        if "/data/scratch/" in p and "*" in p:
            return True
    return False

def create_marker():
    """Create marker file in the current directory (already set up by run_probe.sh)."""
    cwd = os.getcwd()
    with open("PROBE_MARKER", "w") as f:
        f.write(f"created={datetime.datetime.now().isoformat()}\n")
        f.write(f"job_id={MY_ID}\n")
        f.write(f"pid={os.getpid()}\n")
        f.write(f"cwd={cwd}\n")
    print(f"MARKER_CREATED cwd={cwd} time={datetime.datetime.now().isoformat()}")

def create_parent_sentinel():
    """Sentinel in $TMPDIR (the parent Nextflow would remove as a whole)."""
    try:
        with open(os.path.join(PARENT_DIR, "PROBE_PARENT_SENTINEL"), "w") as f:
            f.write(f"job_id={MY_ID}\npid={os.getpid()}\n")
        print(f"PARENT_SENTINEL_CREATED path={PARENT_DIR}/PROBE_PARENT_SENTINEL")
    except Exception as e:
        print(f"PARENT_SENTINEL_ERROR {e}")

def check_marker():
    """Return (exists, content) for the marker file."""
    try:
        with open(os.path.join(SCRATCH_DIR, "PROBE_MARKER"), "r") as f:
            content = f.read().strip()
        return True, content
    except FileNotFoundError:
        return False, ""
    except Exception as e:
        return False, f"ERROR: {e}"

def state():
    return {
        "scratch_dir": os.path.isdir(SCRATCH_DIR),
        "parent_dir": os.path.isdir(PARENT_DIR),
        "parent_sentinel": os.path.isfile(os.path.join(PARENT_DIR, "PROBE_PARENT_SENTINEL")),
    }

def main():
    # ---- Phase 1: create marker ----
    print(f"PARENT_DIR={PARENT_DIR}")
    print(f"SCRATCH_DIR={SCRATCH_DIR}")
    create_marker()
    create_parent_sentinel()
    marker_exists_after_create, _ = check_marker()
    print(f"MARKER_CHECK_1 exists={marker_exists_after_create}")

    # write some filler files to keep busy (relative to cwd = NXF scratch)
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
    vanish = None
    seen_rm = set()
    while time.time() - start < HOLD_S:
        st = state()
        if vanish is None and (not st["scratch_dir"] or not st["parent_sentinel"]):
            vanish = (datetime.datetime.now().isoformat(), st)
            print(f"SCRATCH_VANISHED time={vanish[0]} state={st}")

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
                if "/data/scratch" not in argv:
                    continue
                key = (p, argv)
                if key not in seen_rm:
                    seen_rm.add(key)
                    own = argv_touches_me(argv)
                    print(f"EPILOG_RM own={own} pid={p} comm={comm} argv={argv}")
                if argv_touches_me(argv):
                    if not caught:
                        print(f"FOUND_OWN_CWD = ({SCRATCH_DIR}) in child of epilog: {argv}")
                        print(f"Ancestry_chain = {ancestry_chain(info, ppid)}")
                        caught = True

                        # live job state
                        print("--- live job state ---")
                        output = os.popen(f'{SCTL} show job {MY_ID}').read()
                        print(f"scontrol output = {output}")
                        print("--- / end live job state ---")

            st = state()
            if vanish is None and (not st["scratch_dir"] or not st["parent_sentinel"]):
                vanish = (datetime.datetime.now().isoformat(), st)
                print(f"SCRATCH_VANISHED time={vanish[0]} state={st}")

            if caught:
                break
            time.sleep(0.001)
        if caught:
            break

    # ---- Phase 3: check marker ----
    # small pause so filesystem ops settle
    time.sleep(0.5)
    marker_exists_final, marker_content = check_marker()
    final_state = state()
    print(f"MARKER_CHECK_FINAL exists={marker_exists_final}")
    print(f"FINAL_STATE {final_state}")
    if marker_exists_final:
        print(f"MARKER_CONTENT = {marker_content}")
    else:
        print("MARKER_WIPED = True — epilog deleted our marker while we were still running!")
    if not final_state["scratch_dir"]:
        print("SCRATCH_WIPED = True — nxf.* directory disappeared while we were still running!")
    if not final_state["parent_sentinel"]:
        print("PARENT_WIPED = True — whole /data/scratch/<jobid> disappeared while we were still running!")

    # ---- Phase 4: summary ----
    print("=" * 60)
    exit_code = 0
    wiped = (not marker_exists_final) or (not final_state["scratch_dir"])
    if caught and wiped:
        print("CONCRETE_EVIDENCE: caught epilog rm + scratch/marker wiped = wipe-while-running confirmed")
        exit_code = 1
    elif caught and not wiped:
        print("PARTIAL_EVIDENCE: caught epilog rm but marker survived")
    elif vanish is not None and not wiped:
        print(f"TRANSIENT_VANISH: scratch disappeared and reappeared? at {vanish[0]}")
    elif (not caught) and wiped:
        print("MARKER_MISSING_BUT_NOT_CAUGHT: marker gone but epilog not observed live")
    else:
        print("NO_EVIDENCE: marker survived and epilog not observed")
    print("=" * 60)

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
