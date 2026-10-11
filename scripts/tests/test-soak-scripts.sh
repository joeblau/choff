#!/bin/sh
# Tests for scripts/soak/leaks-report.py (the soak test's leak verdict, #76)
# and the argument handling of scripts/soak/soak.sh. Hermetic: recorded
# `leaks` output in a temporary directory; never runs xcodebuild, a
# simulator or `leaks`. Run with `make test-scripts`.

set -u

scripts_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
report="$scripts_dir/soak/leaks-report.py"
soak="$scripts_dir/soak/soak.sh"

work=$(mktemp -d "${TMPDIR:-/tmp}/blau-soak-tests.XXXXXX")
trap 'rm -rf "$work"' EXIT

passed=0
failed=0

pass() { passed=$((passed + 1)); echo "ok   - $1"; }
fail() { failed=$((failed + 1)); echo "FAIL - $1"; }

# expect <description> <expected exit status> <command...>
expect() {
    description=$1
    expected_status=$2
    shift 2
    "$@" >"$work/out" 2>"$work/err"
    actual=$?
    if [ "$actual" -eq "$expected_status" ]; then
        pass "$description"
    else
        fail "$description (exit $actual, expected $expected_status)"
        sed 's/^/       /' "$work/out" "$work/err"
    fi
}

# expect_output <description> <text the last command's stdout must contain>
expect_output() {
    if grep -qF -- "$2" "$work/out"; then
        pass "$1"
    else
        fail "$1 (no '$2' in the output)"
        sed 's/^/       /' "$work/out"
    fi
}

# What `leaks <pid>` prints (macOS 27), trimmed.
leaks_output() {
    cat <<EOF
Process:         Blau [$1]
Path:            /Users/me/Library/Developer/CoreSimulator/Devices/ABC/data/Containers/Bundle/Application/DEF/Choff.app/Blau
Identifier:      com.joeblau.choff
Platform:        iOS Simulator

leaks Report Version: 4.0, multi-line stacks
Process $1: 51234 nodes malloced for 9876 KB
Process $1: $2 leaks for $3 total leaked bytes.

EOF
}

# --- parse -----------------------------------------------------------------------

leaks_output 4242 3 1536 >"$work/leaks-1.txt"
expect "parse reads the leak summary" 0 \
    python3 -I "$report" parse --phase during-run --wall 120 --input "$work/leaks-1.txt"
expect_output "parse reports the count" '"leaks": 3'
expect_output "parse reports the bytes" '"bytes": 1536'
expect_output "parse reports the process" '"process": "Blau"'
expect_output "parse keeps the phase" '"phase": "during-run"'

leaks_output 4242 1 16 | sed 's/ leaks for / leak for /' >"$work/leaks-singular.txt"
expect "parse reads a single leak" 0 \
    python3 -I "$report" parse --phase during-run --wall 10 --input "$work/leaks-singular.txt"
expect_output "a single leak is counted" '"leaks": 1'

echo "leaks: Failed to inspect process 4242: (ipc/send) invalid destination port" >"$work/leaks-error.txt"
expect "parse fails on output without a summary" 1 \
    python3 -I "$report" parse --phase during-run --wall 10 --input "$work/leaks-error.txt"

# --- evaluate --------------------------------------------------------------------

reading() { python3 -I "$report" parse --phase "$1" --wall "$2" --input "$3"; }

leaks_output 4242 3 1536 >"$work/a.txt"
leaks_output 4242 3 1536 >"$work/b.txt"
leaks_output 4242 3 1536 >"$work/c.txt"
{
    reading during-run 120 "$work/a.txt"
    reading during-run 240 "$work/b.txt"
    reading after-run 400 "$work/c.txt"
} >"$work/flat.jsonl"
expect "evaluate passes when leaks stay flat" 0 \
    python3 -I "$report" evaluate --readings "$work/flat.jsonl" --json "$work/flat.json" --markdown "$work/flat.md"
expect_output "the verdict says no growth" "pass, no growth"
expect_output "the table lists every reading" "| after-run | 6.7 min | 3 | 1,536 |"
if [ -s "$work/flat.json" ] && [ -s "$work/flat.md" ]; then pass "evaluate writes JSON and Markdown"; else fail "evaluate writes JSON and Markdown"; fi

leaks_output 4242 9 4608 >"$work/d.txt"
{
    reading during-run 120 "$work/a.txt"
    reading after-run 400 "$work/d.txt"
} >"$work/growing.jsonl"
expect "evaluate fails when leaks grow" 1 python3 -I "$report" evaluate --readings "$work/growing.jsonl"
expect_output "the growth is reported" "leaks grew by 6 (+3072 bytes) between during-run and after-run"
expect "a tolerance allows small growth" 0 \
    python3 -I "$report" evaluate --readings "$work/growing.jsonl" --tolerance-leaks 6 --tolerance-bytes 4096

# Readings out of order are sorted by time: fewer leaks later is fine.
{
    reading after-run 400 "$work/a.txt"
    reading during-run 120 "$work/d.txt"
} >"$work/shrinking.jsonl"
expect "evaluate passes when leaks shrink" 0 python3 -I "$report" evaluate --readings "$work/shrinking.jsonl"

reading after-run 400 "$work/a.txt" >"$work/single.jsonl"
expect "evaluate is inconclusive with one reading" 2 python3 -I "$report" evaluate --readings "$work/single.jsonl"
expect "evaluate is inconclusive with none" 2 python3 -I "$report" evaluate --readings "$work/missing.jsonl"

# --- soak.sh ---------------------------------------------------------------------

if bash -n "$soak"; then pass "soak.sh parses"; else fail "soak.sh parses"; fi
if [ -x "$soak" ] && [ -x "$report" ]; then pass "the soak scripts are executable"; else fail "the soak scripts are executable"; fi
expect "soak.sh fails cleanly on an unknown simulator" 1 \
    env SIMCTL_DEVICES_JSON=/dev/null DESTINATION='platform=iOS Simulator,name=No Such Phone' \
    SOAK_OUTPUT="$work/soak" "$soak"

# The profiling exception must never hide a crash, missing evidence,
# correctness regression or leak growth. Exercise its acceptance boundary.
expect "profiled verdict accepts only measurement failures" 0 \
    python3 -I - "$scripts_dir/soak/check-profiled-run.py" <<'PY'
import copy
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("profiled", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
names = sorted(module.MEASUREMENTS | module.CORRECTNESS)
report = {"checks": [{"name": name, "passed": True} for name in names],
          "setup": {"audioSeconds": 1204.22}, "samples": [{}, {}, {}]}
leaks = {"passed": True, "toleranceLeaks": 0, "toleranceBytes": 0,
         "readings": [{"pid": 42, "phase": "during-run", "wall": 20, "leaks": 2, "bytes": 64},
                      {"pid": 42, "phase": "after-run", "wall": 140, "leaks": 2, "bytes": 64}]}
summary = {"totalTestCount": 1, "skippedTests": 0, "expectedFailures": 0,
           "passedTests": 1, "failedTests": 0, "testFailures": []}
module.validate(report, leaks, summary, 20, 0)
module.validate_quantitative(report, summary, 20, 0)
for name in names:
    invalid = copy.deepcopy(report)
    invalid["checks"][names.index(name)]["passed"] = False
    try:
        module.validate_quantitative(invalid, summary, 20, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("quantitative gate ignored " + name)
for field, value in [("skippedTests", 1), ("totalTestCount", 0), ("passedTests", 0)]:
    invalid = dict(summary, **{field: value})
    try:
        module.validate_quantitative(report, invalid, 20, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("quantitative gate accepted invalid " + field)
report["checks"][names.index("memory.slope")]["passed"] = False
summary.update(passedTests=0, failedTests=1, testFailures=[{
    "testIdentifierString": "SoakTests/testLongSession()",
    "failureText": 'XCTAssertEqual failed: ("failed: memory.slope") is not equal to ("passed") - The soak failed; see the attached report',
}])
module.validate(report, leaks, summary, 20, 2)

def rejects(change):
    r, l, s = copy.deepcopy((report, leaks, summary))
    change(r, l, s)
    try:
        module.validate(r, l, s, 20, 2)
    except (ValueError, KeyError):
        return
    raise AssertionError("invalid profiling run accepted")

rejects(lambda r, l, s: r["checks"].pop())
rejects(lambda r, l, s: r["checks"][names.index("conversation.complete")].update(passed=False))
rejects(lambda r, l, s: r["setup"].update(audioSeconds=1199))
rejects(lambda r, l, s: s.update(totalTestCount=2))
rejects(lambda r, l, s: s.update(skippedTests=1))
rejects(lambda r, l, s: s["testFailures"][0].update(failureText="The runner crashed"))
rejects(lambda r, l, s: s["testFailures"][0].update(testIdentifierString="OtherTests/testOther()"))
rejects(lambda r, l, s: l["readings"].pop())
rejects(lambda r, l, s: l["readings"][-1].update(pid=43))
rejects(lambda r, l, s: l["readings"][-1].update(bytes=96))
rejects(lambda r, l, s: l.update(toleranceBytes=32))
rejects(lambda r, l, s: l.update(passed=False))
print("complete runs accepted; every quantitative failure, skips, missing tests and 12 invalid profiling runs rejected")
PY

echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
