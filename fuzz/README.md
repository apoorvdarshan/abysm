# Fuzzing

Coverage-guided fuzz targets for the release tooling, run with
[Atheris](https://github.com/google/atheris) (libFuzzer for Python). Each target
checks properties the release pipeline depends on, not just that nothing
crashes:

| Target | Code under test | Property |
| --- | --- | --- |
| `redact_logs_fuzz.py` | `scripts/store/redact_logs.py` | No App Store Connect key ID or issuer ID survives log redaction in UTF-8 or UTF-16, and for any secret value the folder is either clean or the file is deleted (fails closed). |
| `release_gates_fuzz.py` | `resolve_gates()` in `scripts/store/ios_release.py` | Invalid switch or number values are always rejected. Manual runs never publish. Tag runs need exactly `v<MARKETING_VERSION>`. Nothing is published with the master switch off. Review needs this run's upload, and public release needs review. |
| `release_notes_fuzz.py` | `scripts/release_notes.py` | The chosen GitHub Release notes are exactly the tag's single `## <tag>` section. `Unreleased` is never published. Only a duplicated section raises an error. |

## Running

Atheris ships wheels only for Linux x86_64 (CPython 3.12–3.14):

```sh
python3 -m pip install --require-hashes -r fuzz/requirements.txt
python3 fuzz/redact_logs_fuzz.py -max_total_time=60
python3 fuzz/release_gates_fuzz.py -max_total_time=60
python3 fuzz/release_notes_fuzz.py -max_total_time=60
```

Any libFuzzer flag works, for example `-runs=100000` or `-artifact_prefix=out/`.
A failing input is saved as `crash-<sha1>`. Replay it with
`python3 fuzz/<target>.py crash-<sha1>`.

[`fuzz.yml`](../.github/workflows/fuzz.yml) runs every target for 60 seconds on
pull requests and pushes to `main` that touch `scripts/` or `fuzz/`, and for
10 minutes each in a weekly scheduled run. Failing inputs are kept as a workflow
artifact.
