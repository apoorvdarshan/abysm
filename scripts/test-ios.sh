#!/bin/bash
# Builds ABYSM for the iOS Simulator and runs the unit (AbysmTests) and UI
# (AbysmUITests) suites. Unsigned simulator tests only: this script never
# archives, signs or publishes an app.
#
# The unit tests run inside the app (their test host), and the UI tests launch
# that same app. Running both in one `xcodebuild test` made the first UI test
# race the still-running host's shutdown ("Failed to get background assertion
# for target app"). So the app is built once, the unit tests run, the host is
# stopped and confirmed gone, and only then do the UI tests start from a cold
# launch. The UI tests run even when unit tests fail, but never while the host
# may still be running (if it cannot be confirmed gone, the run fails). There
# are no retries.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

app_bundle_id="com.apoorvdarshan.Abysm"
derived_data="${IOS_TEST_DERIVED_DATA:-$HOME/Library/Developer/Xcode/DerivedData/Abysm-simulator-tests}"
packages="${IOS_TEST_PACKAGES:-$derived_data/SourcePackages}"
results="${IOS_TEST_RESULTS:-$derived_data/TestResults/$(date -u +%Y%m%dT%H%M%SZ)-$$}"
mkdir -p "$results"
if compgen -G "$results/*.xcresult" > /dev/null; then
  echo 'Choose an unused IOS_TEST_RESULTS directory; existing results are preserved.' >&2
  exit 1
fi

xcodebuild -version

# Create a task-owned simulator: never erase or reset a developer's existing one.
simulator_id="$(python3 - <<'PY'
import json, subprocess
data = json.loads(subprocess.check_output(['xcrun', 'simctl', 'list', '--json']))
def version(runtime):
    return tuple(int(part) for part in runtime['version'].split('.'))
runtimes = [r for r in data['runtimes'] if r.get('isAvailable') and
            '.iOS-' in r['identifier'] and version(r) >= (17, 0)]
if not runtimes:
    raise SystemExit('Install an iOS 17 or newer Simulator runtime in Xcode.')
runtime = max(runtimes, key=version)
iphones = [d for d in runtime.get('supportedDeviceTypes', []) if d.get('productFamily') == 'iPhone']
if not iphones:
    raise SystemExit('Selected runtime has no supported iPhone device type.')
preferred = ('iPhone 17 Pro', 'iPhone 16 Pro', 'iPhone 17', 'iPhone 16')
device = next((d for name in preferred for d in iphones if d['name'] == name), iphones[-1])
print(subprocess.check_output(['xcrun', 'simctl', 'create', 'ABYSM CI',
      device['identifier'], runtime['identifier']], text=True).strip())
PY
)"

# shellcheck disable=SC2329 # called by the EXIT trap
cleanup() {
  # Only the simulator created by this invocation is removed.
  xcrun simctl shutdown "$simulator_id" >/dev/null 2>&1 || true
  xcrun simctl delete "$simulator_id" >/dev/null 2>&1 || true
}
trap cleanup EXIT

common=(
  -project Abysm.xcodeproj
  -scheme Abysm
  -configuration Debug
  -destination "platform=iOS Simulator,id=$simulator_id"
  -destination-timeout 120
  -derivedDataPath "$derived_data"
  -clonedSourcePackagesDirPath "$packages"
  -onlyUsePackageVersionsFromResolvedFile
)

summarize() {
  grep -E '(error|warning): |Test (Case|Suite) .*(passed|failed)|Executed [0-9]+ test|\*\* (TEST|BUILD)' "$1" \
    | grep -vE "^Test Suite '(All tests|Selected tests)'" || true
}

build_status=0
xcodebuild build-for-testing "${common[@]}" CODE_SIGNING_ALLOWED=NO > "$results/build.log" 2>&1 || build_status=$?
summarize "$results/build.log"
if (( build_status != 0 )); then
  tail -n 40 "$results/build.log"
  echo "error: the build for testing failed (log: $results/build.log)" >&2
  exit "$build_status"
fi

# One bundle per run; failures keep their screenshots and logs in the result
# bundle (the extra simulator sysdiagnose is skipped: it can stall for minutes).
run_bundle() {
  local bundle="$1" name="$2" status=0
  xcodebuild test-without-building "${common[@]}" \
    -only-testing:"$bundle" \
    -resultBundlePath "$results/$name.xcresult" \
    -parallel-testing-enabled NO \
    -collect-test-diagnostics never \
    > "$results/$name.log" 2>&1 || status=$?
  summarize "$results/$name.log"
  if (( status != 0 )); then
    tail -n 40 "$results/$name.log"
    echo "error: $bundle failed (log and result bundle: $results)" >&2
  fi
  return "$status"
}

# Whether the simulator still lists the app. The job list is read whole before it
# is searched: piped into `grep -q` under pipefail, an early match let grep quit,
# launchctl died of SIGPIPE, and a running app read as gone. A list that cannot
# be read stops the run, since the UI tests must not start without knowing.
app_running() {
  local launchd_jobs list_status=0
  launchd_jobs="$(xcrun simctl spawn "$simulator_id" launchctl list 2>/dev/null)" || list_status=$?
  if (( list_status != 0 )); then
    echo "error: cannot list the simulator's launchd jobs (exit $list_status); not starting the UI tests" >&2
    exit 1
  fi
  [[ "$launchd_jobs" == *"UIKitApplication:${app_bundle_id}["* ]]
}

status=0
run_bundle AbysmTests UnitTests || status=1

# Stop the unit-test host and wait until it is gone, so the first UI test
# launches the app cleanly instead of racing the host's shutdown.
xcrun simctl terminate "$simulator_id" "$app_bundle_id" >/dev/null 2>&1 || true
for _ in $(seq 1 60); do
  app_running || break
  sleep 0.5
done
if app_running; then
  echo "error: the unit-test host app did not exit; not starting the UI tests" >&2
  exit 1
fi

run_bundle AbysmUITests UITests || status=1

# Both suites must have run: a passing run with zero tests is a failure.
python3 - "$results" <<'PY'
import json, subprocess, sys
results = sys.argv[1]
counts = {}
def walk(node, bundle=None):
    kind = node.get('nodeType', '')
    if kind.endswith('test bundle'):
        bundle = node.get('name')
    if kind == 'Test Case':
        counts.setdefault(bundle, {}).setdefault(node.get('result', '?'), 0)
        counts[bundle][node.get('result', '?')] += 1
    for child in node.get('children', []):
        walk(child, bundle)
for name in ('UnitTests', 'UITests'):
    try:
        tree = json.loads(subprocess.check_output(
            ['xcrun', 'xcresulttool', 'get', 'test-results', 'tests',
             '--path', f'{results}/{name}.xcresult', '--format', 'json']))
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f'error: cannot read {name}.xcresult: {exc}', file=sys.stderr)
        continue
    for node in tree.get('testNodes', []):
        walk(node)
failed = False
for bundle in ('AbysmTests', 'AbysmUITests'):
    outcomes = counts.get(bundle, {})
    ran = sum(outcomes.values())
    print(f'{bundle}: {ran} tests {outcomes}')
    if ran == 0 or outcomes.get('Passed', 0) == 0:
        print(f'error: {bundle} ran no passing tests', file=sys.stderr)
        failed = True
    if any(result not in ('Passed', 'Expected Failure') for result in outcomes):
        failed = True
sys.exit(1 if failed else 0)
PY
echo "result bundles: $results/UnitTests.xcresult $results/UITests.xcresult"
exit "$status"
