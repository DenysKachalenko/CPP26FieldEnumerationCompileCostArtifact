#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# One unattended night of the final campaign (RunBook.md steps 1-4b). Started once, in Git
# Bash, and needs no input afterwards:
#
#   bash overnight.sh S1        # on another day:  bash overnight.sh S2
#   bash overnight.sh S2 sleep  # the same, then put the PC to sleep when the night ends
#   bash overnight.sh S3 sleep  # supplementary session: job FrontendIdiom, GCC 16.2.0 only
#
# Steps (log: Data/Overnight/<session>.log; current state: Data/Overnight/<session>.status):
#   1. GCC 16.2.0: installed already, or a build started earlier the same evening is waited
#      for, or build_gcc.sh runs now.
#   2. CMake build + CTest with GCC 16.2.0, and the library pins (deps.py verify).
#   3. High performance power plan (the previous plan is restored at exit) and a keep-awake
#      request for the whole night.
#   4. The Boost.PFR probe, once (skipped while Data/PfrProbe.json holds a non-pilot result),
#      then a smoke test of the session runner in a scratch directory (a few minutes).
#   5. The session, every job. Nothing waits for a quiet machine: the load is recorded with
#      every compile. A crash is resumed (at most the current round is lost). A failed
#      preflight, a refused resume, a failed job or Ctrl+C stops the night.
# Nothing here changes what is measured: the session itself enforces its protocol.
set -uo pipefail

SESSION=${1:?usage: bash overnight.sh S1|S2|S3 [rehearse|sleep]}
# "rehearse": every step up to the probe and the session (checks, build, CMake/CTest, pins,
# power plan and its restore), then stop; logged separately.
# "sleep": put the PC to sleep (ACPI sleep, not hibernation) when the night ends, completed or
# stopped (not on Ctrl+C).
MODE=${2:-}
REHEARSE=""
[ "${MODE}" = rehearse ] && REHEARSE=rehearse
HERE=$(cd "$(dirname "$0")" && pwd)
PROJECT=$(dirname "${HERE}")
# Session names are upper case (Data/Sessions is case-insensitive on NTFS), and a session that
# completed is never run again. Checked before anything is written to its log or status.
SESSION=${SESSION^^}
if grep -qs "session complete" "${PROJECT}/Data/Sessions/${SESSION}/log.txt"; then
	echo "session ${SESSION} is complete (Data/Sessions/${SESSION}/log.txt); it is not run again" >&2
	exit 2
fi
PY=${PY:-/c/Users/kacha/AppData/Local/Programs/Python/Python313/python.exe}
G162=C:/msys64/home/kacha/gcc-16.2.0-install/bin/g++.exe
G161=C:/msys64/home/kacha/gcc-16-install/bin/g++.exe
G152=C:/msys64/ucrt64/bin/g++.exe
PROVENANCE=/c/msys64/home/kacha/gcc-16.2.0-install/PROVENANCE.txt
BUILD_STATUS=/c/msys64/home/kacha/gcc-builds/16.2.0.status.log
HIGH_PERFORMANCE=8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
OUT=${PROJECT}/Data/Overnight
# What the session runs: S1 and S2 the full plan on both compilers; S3 (supplementary,
# 2026-11-20) only the job FrontendIdiom on GCC 16.2.0.
SESSION_ARGS=(--compiler "GCC161=${G161}")
SMOKE_ARGS=(--compiler "GCC161=${G161}" --jobs OverloadK,CompilerHeavy)
if [ "${SESSION}" = S3 ]; then
	SESSION_ARGS=(--jobs FrontendIdiom)
	SMOKE_ARGS=(--jobs FrontendIdiom)
fi
LOG=${OUT}/${SESSION}${REHEARSE:+-${REHEARSE}}.log
STATUS=${OUT}/${SESSION}${REHEARSE:+-${REHEARSE}}.status
export PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
mkdir -p "${OUT}"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }
state() { echo "[$(date '+%F %T')] $*" > "${STATUS}"; log "STATE: $*"; }
stop() { state "STOPPED: $*"; exit 1; }
# Run a command with its output on the console and in the log; return its exit code.
run() { log "\$ $*"; "$@" 2>&1 | tee -a "${LOG}"; return "${PIPESTATUS[0]}"; }

ORIGINAL_SCHEME=""
AWAKE_PID=""
INTERRUPTED=0
cleanup() {
	if [ -n "${ORIGINAL_SCHEME}" ]; then
		MSYS_NO_PATHCONV=1 powercfg /setactive "${ORIGINAL_SCHEME}" && log "power plan restored (${ORIGINAL_SCHEME})"
	fi
	[ -n "${AWAKE_PID}" ] && kill "${AWAKE_PID}" 2>/dev/null
	if [ "${MODE}" = sleep ] && [ "${INTERRUPTED}" = 0 ]; then
		log "putting the PC to sleep"
		# Not rundll32 SetSuspendState: with hibernation enabled it hibernates instead of sleeping.
		powershell.exe -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; \
[System.Windows.Forms.Application]::SetSuspendState([System.Windows.Forms.PowerState]::Suspend, \$false, \$false)" >/dev/null 2>&1
	fi
}
trap cleanup EXIT
trap 'INTERRUPTED=1; log "interrupted"; exit 130' INT TERM

# Waits until the whole-machine CPU load, averaged over 30 s, is at most 5% (the session's
# own start limit). $1 = minutes before giving up.
wait_quiet() {
	"${PY}" - "$1" <<'EOF'
import sys, time, psutil
deadline = time.time() + 60 * float(sys.argv[1])
while True:
    procs = list(psutil.process_iter(["name", "pid"]))
    for p in procs:
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    load = psutil.cpu_percent(interval=30)
    if load <= 5.0:
        print(f"machine quiet: {load:.1f}% over 30 s", flush=True)
        sys.exit(0)
    usage = []
    for p in procs:
        try:
            if p.info["pid"]:
                usage.append((p.cpu_percent(None) / psutil.cpu_count(), p.info["name"]))
        except psutil.Error:
            pass
    busiest = ", ".join(f"{n} {c:.1f}%" for c, n in sorted(usage, reverse=True)[:3])
    print(f"waiting for a quiet machine: {load:.1f}% ({busiest})", flush=True)
    if time.time() > deadline:
        sys.exit(1)
EOF
}

build_running() {
	[ "$(powershell.exe -NoProfile -Command "@(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like ('*build_gcc' + '.sh*') }).Count" | tr -d '\r ')" != 0 ]
}

state "start: session ${SESSION}"
log "python ${PY}; project ${PROJECT}"
"${PY}" -c "import psutil, numpy" || stop "python ${PY} lacks psutil/numpy"
# S3 does not use GCC 16.1.0.
[ "${SESSION}" = S3 ] || [ "$("${G161}" -dumpfullversion)" = 16.1.0 ] || stop "${G161} is not GCC 16.1.0"
# Mem Reduct empties working sets every 15 minutes; it must not run during measurement.
# (It starts again at the next login.)
if tasklist //FI "IMAGENAME eq memreduct.exe" 2>/dev/null | grep -qi memreduct.exe; then
	taskkill //IM memreduct.exe //F >/dev/null 2>&1 && log "closed Mem Reduct for the night"
fi

# 1. GCC 16.2.0.
if [ ! -f "${PROVENANCE}" ] && build_running; then
	state "waiting for the GCC 16.2.0 build started earlier"
	deadline=$((SECONDS + 4 * 3600))
	while build_running && [ ! -f "${PROVENANCE}" ] && [ "${SECONDS}" -lt "${deadline}" ]; do sleep 60; done
	log "build status: $(tail -1 "${BUILD_STATUS}" 2>/dev/null)"
fi
if [ ! -f "${PROVENANCE}" ]; then
	state "building GCC 16.2.0"
	run /c/msys64/usr/bin/env.exe MSYSTEM=UCRT64 /usr/bin/bash -lc \
		"bash /e/Science/Programs/SerializationCompileCost/Harness/build_gcc.sh" \
		|| log "build_gcc.sh failed: $(tail -1 "${BUILD_STATUS}" 2>/dev/null)"
fi
[ -f "${PROVENANCE}" ] || stop "GCC 16.2.0 is not built (see ${BUILD_STATUS})"
[ "$("${G162}" -dumpfullversion)" = 16.2.0 ] || stop "${G162} does not report 16.2.0"

# 2. The build, the tests and the pins with GCC 16.2.0.
state "CMake build and CTest with GCC 16.2.0"
cd "${PROJECT}" || stop "no project directory"
# The pinned library trees already unpacked and verified by deps.py, not a download at night.
PINS=$("${PY}" -c "import sys; sys.path.insert(0, 'Harness'); import deps
print(' '.join(f'-DFETCHCONTENT_SOURCE_DIR_{n.upper().replace(\"-\", \"_\")}={deps.source_dir(n, p).as_posix()}' for n, p in deps.load().items()))") \
	|| stop "cannot read the pins"
log "pinned sources: ${PINS}"
# shellcheck disable=SC2086
run cmake --preset gcc16.2-local ${PINS} || stop "cmake configure (gcc16.2-local)"
run cmake --build --preset gcc16.2-local || stop "cmake build (gcc16.2-local)"
run ctest --preset gcc16.2-local || stop "ctest (gcc16.2-local)"
cd "${HERE}" || stop "no harness directory"
run "${PY}" deps.py verify || stop "deps.py verify"

# 3. Power plan and keep-awake.
ORIGINAL_SCHEME=$(MSYS_NO_PATHCONV=1 powercfg /getactivescheme | sed -n 's/.*GUID: \([0-9a-f-]*\).*/\1/p')
MSYS_NO_PATHCONV=1 powercfg /setactive "${HIGH_PERFORMANCE}" || stop "cannot select the High performance plan"
log "power plan: $(MSYS_NO_PATHCONV=1 powercfg /getactivescheme) (was ${ORIGINAL_SCHEME})"
"${PY}" -c "import ctypes, time
ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
while True: time.sleep(3600)" &
AWAKE_PID=$!

if [ "${REHEARSE}" = rehearse ]; then
	wait_quiet 0.6 2>&1 | tee -a "${LOG}"
	state "REHEARSAL DONE: every step before the probe and the session passed"
	exit 0
fi

# 4. The Boost.PFR probe (once).
if [ -f "${PROJECT}/Data/PfrProbe.json" ] && grep -q '"pilot": false' "${PROJECT}/Data/PfrProbe.json"; then
	log "Boost.PFR probe already done (Data/PfrProbe.json)"
elif [ "$("${G152}" -dumpfullversion 2>/dev/null)" != 15.2.0 ]; then
	log "${G152} is not GCC 15.2.0: Boost.PFR probe skipped (it needs 15.2.0)"
else
	state "Boost.PFR probe"
	run "${PY}" pfrprobe.py --gxx "GCC162=${G162}" --gxx "GCC152=${G152}" \
		|| log "Boost.PFR probe failed (exit $?); continuing with the session"
fi

# 4b. A short pilot of the session runner itself (scratch directory, one job, one round, no
#     preflight): the night stops here, before any measurement, if the runner is broken.
state "smoke test of campaign.py"
SMOKE=$(mktemp -d)
export RB_SESSIONS
RB_SESSIONS=$(cygpath -w "${SMOKE}")
run "${PY}" campaign.py run --session Smoke --gxx "${G162}" \
	"${SMOKE_ARGS[@]}" --rounds 1 --warmup 0 --skip-preflight \
	|| stop "smoke test of campaign.py failed"
unset RB_SESSIONS
grep -q "session complete" "${SMOKE}/Smoke/log.txt" || stop "smoke test did not complete"
rm -rf "${SMOKE}"

# 5. The session.
crashes=0
PROGRESS=${PROJECT}/Data/Sessions/${SESSION}/rounds.json
progress_mark() { stat -c %Y "${PROGRESS}" 2>/dev/null || echo none; }
while :; do
	state "session ${SESSION} running (progress: Data/Sessions/${SESSION}/log.txt)"
	before=$(progress_mark)
	run "${PY}" campaign.py run --session "${SESSION}" --gxx "${G162}" "${SESSION_ARGS[@]}"
	code=$?
	case ${code} in
		0) state "DONE: session ${SESSION} complete"; exit 0 ;;
		3) stop "preflight failed (Data/Sessions/${SESSION}/preflight_*.json)" ;;
		4) stop "session refused the resume: compiler, code or protocol differs from session.json" ;;
		5) stop "session incomplete: a job failed (JOB FAILED in Data/Sessions/${SESSION}/log.txt); the other jobs ran" ;;
		6) stop "the power plan is not High performance" ;;
		130) stop "stopped by Ctrl+C" ;;
		*) # A crash; finished rounds are kept. Only crashes without progress in between count.
		   [ "$(progress_mark)" != "${before}" ] && crashes=0
		   crashes=$((crashes + 1))
		   [ "${crashes}" -lt 3 ] || stop "campaign.py exited ${code}, ${crashes} times without progress"
		   log "campaign.py exited ${code}; resuming in 60 s"
		   sleep 60 ;;
	esac
done
