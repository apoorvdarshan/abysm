#!/bin/bash
# Builds ABYSM for the iOS Simulator and runs the unit (AbysmTests) and UI
# (AbysmUITests) suites. Unsigned simulator tests only: this script never
# archives, signs or publishes an app.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

derived_data="${IOS_TEST_DERIVED_DATA:-$HOME/Library/Developer/Xcode/DerivedData/Abysm-simulator-tests}"
packages="${IOS_TEST_PACKAGES:-$derived_data/SourcePackages}"
results="${IOS_TEST_RESULTS:-$derived_data/TestResults/$(date -u +%Y%m%dT%H%M%SZ)-$$}"
mkdir -p "$results"
if [[ -e "$results/Tests.xcresult" ]]; then
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

cleanup() {
  # Only the simulator created by this invocation is removed.
  xcrun simctl shutdown "$simulator_id" >/dev/null 2>&1 || true
  xcrun simctl delete "$simulator_id" >/dev/null 2>&1 || true
}
trap cleanup EXIT

status=0
xcodebuild test \
  -project Abysm.xcodeproj \
  -scheme Abysm \
  -configuration Debug \
  -destination "platform=iOS Simulator,id=$simulator_id" \
  -destination-timeout 120 \
  -derivedDataPath "$derived_data" \
  -clonedSourcePackagesDirPath "$packages" \
  -onlyUsePackageVersionsFromResolvedFile \
  -resultBundlePath "$results/Tests.xcresult" \
  -parallel-testing-enabled NO \
  -collect-test-diagnostics never \
  CODE_SIGNING_ALLOWED=NO \
  > "$results/xcodebuild.log" 2>&1 || status=$?
grep -E '(error|warning): |Test (Case|Suite) .*(passed|failed)|Executed [0-9]+ test|\*\* TEST' \
  "$results/xcodebuild.log" | grep -vE "^Test Suite '(All tests|Selected tests)'" || true
if (( status != 0 )); then
  tail -n 40 "$results/xcodebuild.log"
  echo "error: xcodebuild test failed (log and result bundle: $results)" >&2
  exit "$status"
fi

# Both suites must have run: a passing run with zero tests is a failure.
xcrun xcresulttool get test-results tests --path "$results/Tests.xcresult" --format json \
  > "$results/tests.json"
python3 - "$results/tests.json" <<'PY'
import json, sys
tree = json.load(open(sys.argv[1]))
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
for node in tree.get('testNodes', []):
    walk(node)
failed = False
for bundle in ('AbysmTests', 'AbysmUITests'):
    results = counts.get(bundle, {})
    ran = sum(results.values())
    print(f'{bundle}: {ran} tests {results}')
    if ran == 0 or results.get('Passed', 0) == 0:
        print(f'error: {bundle} ran no passing tests', file=sys.stderr)
        failed = True
    if any(result not in ('Passed', 'Expected Failure') for result in results):
        failed = True
sys.exit(1 if failed else 0)
PY
echo "result bundle: $results/Tests.xcresult"
