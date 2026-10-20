# Fuzzing

Coverage-guided fuzz targets, run with [Atheris](https://github.com/google/atheris)
(libFuzzer for Python), for the
[apoorvdarshan/store-release](https://github.com/apoorvdarshan/store-release) code
ABYSM's release workflows run. They test the commit `ios-release.yml` and
`store-checks.yml` pin, bound to ABYSM's own [`store/store-release.toml`](../store/store-release.toml)
(the `abysm` flow, `v<MARKETING_VERSION>` tags, the `quality` gate job), and each
checks properties the release depends on, not just that nothing crashes:

| Target | Code under test | Properties |
| --- | --- | --- |
| `release_gates_fuzz.py` | `resolve_gates()` and `write_outputs()` in the abysm flow's `ios_release.py`; `stage.gate_check()` and the app-store-connect and github-release stage checks | The switches accept exactly what the documented rules allow (an independent model): invalid values fail even with the master switch off, a tag must be exactly `v<MARKETING_VERSION>`, a manual run or the master switch off publishes nothing, review needs this run's upload and public release needs review. Outputs read back to the plan. Later stages pass only `quality=success` and consistent flags, and pass every plan a tag run resolves. |
| `release_notes_fuzz.py` | `release-notes --if-present <tag>` and `--check-headings` (`release_notes.py`) | The GitHub Release gets exactly the tag's one `## <tag>` section, or nothing (GitHub then generates notes). A repeated or empty section, `Unreleased` or an empty tag fails without printing. The pull request check rejects exactly the repeated headings. Built from ABYSM's real `RELEASE_NOTES.md`. |
| `redact_logs_fuzz.py` | `ios redact-logs` (`redact.py`) | No App Store Connect key ID or issuer ID survives in kept logs, in any ASCII case, as UTF-8 or UTF-16, in contents or file and folder names. For any ASCII IDs it fails closed. Files without an ID are untouched, and nothing outside the folder is written through a symbolic link. |
| `config_fuzz.py` | `config.load_for_app()` and `context.configure()` with ABYSM's config, and `paths.patterns()` | Only `ConfigError` is raised. Every path the abysm flow is bound to (constants and function defaults) stays inside the app checkout, with nothing left unconfigured. Tag prefix, bundle id, app id and gate jobs are safe and as configured. Every job's sparse-checkout patterns are rooted, single-line and never leave the checkout. |

## Running

Atheris ships wheels only for Linux x86-64 (CPython 3.12 to 3.14). The targets
look for the store-release checkout in `.store-release/` at the repository root
(ignored by git), or in `STORE_RELEASE_DIR`. `fuzz/store_release_pin.py` prints
the commit the release workflows pin, fetches it, or checks a checkout against it:

```sh
python3 -I fuzz/store_release_pin.py --fetch .store-release   # the pinned commit, checked
python3 -m pip install --require-hashes -r fuzz/requirements.txt
python3 -I fuzz/release_gates_fuzz.py -max_total_time=60
python3 -I fuzz/release_notes_fuzz.py -max_total_time=60
python3 -I fuzz/redact_logs_fuzz.py -max_total_time=60
python3 -I fuzz/config_fuzz.py -max_total_time=60
```

Any libFuzzer flag works, for example `-runs=100000` or `-artifact_prefix=out/`.
A failing input is saved as `crash-<sha1>`; replay it with
`python3 -I fuzz/<target>_fuzz.py crash-<sha1>`.

[`fuzz.yml`](../.github/workflows/fuzz.yml) runs every target for 60 seconds on
pull requests and pushes to `main` that touch `fuzz/`, the config, the release
notes, the Xcode project or the store-release pin, for 10 minutes each in a
weekly run, and for the seconds you ask for in a manual run. It is advisory, not
a required check. Failing inputs are kept as a workflow artifact for 14 days.

When Dependabot moves the store-release pin, these targets run against the new
commit in that pull request. A target that fails at startup with an assertion
about a switch, bound or gate job means store-release changed something these
properties describe: update the target together with the pin.
