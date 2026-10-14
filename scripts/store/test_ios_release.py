#!/usr/bin/env python3
"""Offline tests for ABYSM's iOS release switches, build waiting, listing and review.

No network: every App Store Connect call goes to an in-memory fake. Also checks
scripts/test-ios.sh's wait for the unit-test host app to exit, against a fake
xcrun (no simulator).
Run: python3 -m unittest discover -s scripts/store -p 'test_*.py'

Release runs (ios-release.yml's prepare job) set STORE_TESTS_SCOPE=release. The
tests that check repository content a release may not use (the listing and
screenshots, other tags' release notes) are then skipped: a release checks the
listing and screenshots only when their switch is on (the gated
`asc_release.py --dry-run`) and only its own release notes, so unused files
never block a build-only release. Pull requests and main (store-checks.yml) run
every test.
"""
from __future__ import annotations

import argparse
import datetime as dt
import http.client
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))

import asc_release  # noqa: E402
import export_listing  # noqa: E402
import ios_release  # noqa: E402
import print_gates  # noqa: E402
import redact_logs  # noqa: E402
import release_notes  # noqa: E402
import validate_catalog  # noqa: E402
from ios_release import ReleaseError, resolve_gates  # noqa: E402

RELEASE_SCOPE = os.environ.get("STORE_TESTS_SCOPE") == "release"
# Checks of repository content a release may not use: the listing and screenshots
# (checked by the gated dry run when their switch is on) and other tags' release
# notes (the tag's own section is checked by the "Check release notes" step).
repo_content = unittest.skipIf(RELEASE_SCOPE, "release run: checked only when this release uses it")
REPO_CONTENT_TESTS = (
    "ScreenshotPlanTests.test_repo_marketing_images_are_app_store_ready",
    "ListingTests.test_repo_metadata_is_valid_for_every_switch_but_whats_new",
    "AscCliTests.test_full_dry_run_with_repo_inputs",
    "ReleaseNotesTests.test_repository_release_notes_have_one_section_per_heading",
)

TAG = "v1.0.1"
VERSION = "1.0.1"
APP = asc_release.APP_STORE_APP_ID
ALL_ON = {
    "IOS_RELEASE_AUTOMATION": "true",
    "IOS_UPLOAD_BUILD": "true",
    "IOS_UPLOAD_LISTING": "true",
    "IOS_UPLOAD_WHATS_NEW": "true",
    "IOS_UPLOAD_SCREENSHOTS": "true",
    "IOS_SUBMIT_REVIEW": "true",
    "IOS_PUBLIC_RELEASE": "true",
}
OPS = ("upload_build", "listing", "whats_new", "screenshots", "submit", "public_release")
ASC_FLAGS = {"UPLOAD_LISTING", "UPLOAD_WHATS_NEW", "UPLOAD_SCREENSHOTS", "SUBMIT_IOS_REVIEW", "PUBLIC_RELEASE"}


def quiet(fn, *args, **kwargs):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def gates(env: dict[str, str], *, event: str = "push", ref: str = TAG, version: str = VERSION) -> dict:
    return resolve_gates(env, event=event, ref_name=ref, marketing_version=version)


class GateTests(unittest.TestCase):
    def test_missing_settings_mean_everything_off(self) -> None:
        result = gates({})
        self.assertEqual(result["mode"], "release")
        self.assertFalse(result["master"])
        self.assertFalse(result["build"])
        self.assertFalse(result["asc"])
        for key in OPS:
            self.assertFalse(result[key], key)
        self.assertEqual((result["poll_seconds"], result["wait_minutes"]), (30, 120))

    def test_master_off_ignores_operation_switches(self) -> None:
        result = gates({**ALL_ON, "IOS_RELEASE_AUTOMATION": "false"})
        for key in OPS:
            self.assertFalse(result[key], key)
        self.assertFalse(result["build"])
        self.assertTrue(any("ignored" in note for note in result["notes"]))

    def test_each_operation_is_independent(self) -> None:
        result = gates({"IOS_RELEASE_AUTOMATION": "yes", "IOS_UPLOAD_LISTING": "on"})
        self.assertTrue(result["listing"])
        self.assertTrue(result["asc"])
        self.assertFalse(result["whats_new"])
        self.assertFalse(result["upload_build"])
        self.assertFalse(result["build"])
        result = gates({"IOS_RELEASE_AUTOMATION": "1", "IOS_UPLOAD_BUILD": "1"})
        self.assertTrue(result["build"])
        self.assertFalse(result["asc"])

    def test_all_on(self) -> None:
        result = gates(ALL_ON)
        for key in OPS:
            self.assertTrue(result[key], key)
        self.assertTrue(result["build"])
        self.assertTrue(result["master"])

    def test_invalid_values_are_rejected_even_when_master_is_off(self) -> None:
        for name in ("IOS_RELEASE_AUTOMATION", "IOS_UPLOAD_BUILD", "IOS_SUBMIT_REVIEW", "IOS_UPLOAD_WHATS_NEW"):
            for bad in ("maybe", "enabled", "2", "tru"):
                with self.subTest(name=name, bad=bad), self.assertRaisesRegex(ReleaseError, name):
                    gates({name: bad})

    def test_switch_values_are_case_and_space_insensitive(self) -> None:
        result = gates({"IOS_RELEASE_AUTOMATION": " TRUE ", "IOS_UPLOAD_LISTING": "Yes"})
        self.assertTrue(result["listing"])
        self.assertFalse(gates({"IOS_RELEASE_AUTOMATION": "OFF"})["master"])

    def test_bad_timing_values_are_rejected(self) -> None:
        for env in (
            {"IOS_BUILD_POLL_SECONDS": "5"},
            {"IOS_BUILD_POLL_SECONDS": "601"},
            {"IOS_BUILD_POLL_SECONDS": "thirty"},
            {"IOS_BUILD_POLL_SECONDS": "٣٠"},
            {"IOS_BUILD_WAIT_MINUTES": "9"},
            {"IOS_BUILD_WAIT_MINUTES": "301"},
            {"IOS_BUILD_WAIT_MINUTES": "-5"},
        ):
            with self.subTest(env=env), self.assertRaises(ReleaseError):
                gates(env)
        result = gates({"IOS_BUILD_POLL_SECONDS": "45", "IOS_BUILD_WAIT_MINUTES": "90"})
        self.assertEqual((result["poll_seconds"], result["wait_minutes"]), (45, 90))
        result = gates({"IOS_BUILD_POLL_SECONDS": "10", "IOS_BUILD_WAIT_MINUTES": "300"})
        self.assertEqual((result["poll_seconds"], result["wait_minutes"]), (10, 300))

    def test_submit_requires_this_runs_build(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "IOS_UPLOAD_BUILD"):
            gates({"IOS_RELEASE_AUTOMATION": "true", "IOS_SUBMIT_REVIEW": "true"})

    def test_public_release_requires_submit(self) -> None:
        env = {"IOS_RELEASE_AUTOMATION": "true", "IOS_UPLOAD_BUILD": "true", "IOS_PUBLIC_RELEASE": "true"}
        with self.assertRaisesRegex(ReleaseError, "IOS_SUBMIT_REVIEW"):
            gates(env)

    def test_tag_must_be_exactly_v_plus_marketing_version(self) -> None:
        for ref in ("v1.0.2", "v1.0", "v1.0.1-beta.1", "v01.0.1", "v1.0.1.0"):
            with self.subTest(ref=ref), self.assertRaisesRegex(ReleaseError, "does not match"):
                gates({}, ref=ref)
        for ref in ("1.0.1", "ios-v1.0.1", "release-1.0.1", ""):
            with self.subTest(ref=ref), self.assertRaisesRegex(ReleaseError, "tag"):
                gates({}, ref=ref)
        # The historical v1.0.0 tag no longer matches a 1.0 project.
        with self.assertRaisesRegex(ReleaseError, "does not match"):
            gates({}, ref="v1.0.0", version="1.0")
        self.assertEqual(gates({}, ref="v1.0", version="1.0")["marketing_version"], "1.0")

    def test_tag_mismatch_fails_even_with_master_off(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "does not match"):
            gates({"IOS_RELEASE_AUTOMATION": "false"}, ref="v9.9")

    def test_manual_run_validates_only(self) -> None:
        result = gates(ALL_ON, event="workflow_dispatch", ref="main")
        self.assertEqual(result["mode"], "validate")
        self.assertTrue(result["build"])
        self.assertFalse(result["master"])
        self.assertFalse(result["asc"])
        for key in OPS:
            self.assertFalse(result[key], key)

    def test_manual_run_still_rejects_invalid_switches(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "IOS_UPLOAD_LISTING"):
            gates({"IOS_UPLOAD_LISTING": "sure"}, event="workflow_dispatch", ref="main")

    def test_manual_run_can_validate_a_future_version(self) -> None:
        result = resolve_gates({}, event="workflow_dispatch", ref_name="main",
                               marketing_version="1.0", validation_version="1.0.1")
        self.assertEqual(result["mode"], "validate")
        self.assertEqual(result["marketing_version"], "1.0.1")
        self.assertFalse(result["asc"])
        self.assertTrue(any("not changed" in note for note in result["notes"]))
        default = resolve_gates({}, event="workflow_dispatch", ref_name="main", marketing_version="1.0")
        self.assertEqual(default["marketing_version"], "1.0")

    def test_version_override_is_rejected_for_releases_and_bad_values(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "manual validation"):
            resolve_gates({}, event="push", ref_name=TAG, marketing_version=VERSION, validation_version="1.0.2")
        for bad in ("1.x", "v1.0.1", "1.0.1.2", "1.0 beta", "١.٠"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ReleaseError, "must look like"):
                resolve_gates({}, event="workflow_dispatch", ref_name="main",
                              marketing_version=VERSION, validation_version=bad)

    def test_unsupported_event_fails(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "unsupported event"):
            gates({}, event="pull_request")


PBX_TEMPLATE = """
		AAA /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				CURRENT_PROJECT_VERSION = {debug_build};
				MARKETING_VERSION = {debug_version};
				PRODUCT_BUNDLE_IDENTIFIER = com.apoorvdarshan.Abysm;
			}};
			name = Debug;
		}};
		BBB /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				CURRENT_PROJECT_VERSION = {release_build};
				LD_RUNPATH_SEARCH_PATHS = (
					"$(inherited)",
					"@executable_path/Frameworks",
				);
				MARKETING_VERSION = "{release_version}";
				PRODUCT_BUNDLE_IDENTIFIER = com.apoorvdarshan.Abysm;
			}};
			name = Release;
		}};
		CCC /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				CURRENT_PROJECT_VERSION = 1;
				MARKETING_VERSION = 0.9;
				PRODUCT_BUNDLE_IDENTIFIER = com.apoorvdarshan.AbysmTests;
			}};
			name = Debug;
		}};
"""


class ProjectVersionTests(unittest.TestCase):
    def pbx(self, **values: str) -> Path:
        settings = {"debug_build": "7", "release_build": "7", "debug_version": "1.2", "release_version": "1.2"}
        settings.update(values)
        tmp = tempfile.NamedTemporaryFile("w", suffix=".pbxproj", delete=False)
        tmp.write(PBX_TEMPLATE.format(**settings))
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return Path(tmp.name)

    def test_real_project_uses_the_app_target_only(self) -> None:
        version = ios_release.project_marketing_version()
        self.assertRegex(version, r"^\d+(\.\d+){1,2}$")
        self.assertGreaterEqual(ios_release.project_build_number(), 1)
        configs = ios_release.app_build_configurations()
        self.assertEqual(set(configs), {"Debug", "Release"})

    def test_test_targets_do_not_affect_the_release_version(self) -> None:
        path = self.pbx()
        self.assertEqual(ios_release.project_marketing_version(path), "1.2")
        self.assertEqual(ios_release.project_build_number(path), 7)

    def test_debug_and_release_must_agree(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "MARKETING_VERSION"):
            ios_release.project_marketing_version(self.pbx(release_version="1.3"))
        with self.assertRaisesRegex(ReleaseError, "CURRENT_PROJECT_VERSION"):
            ios_release.project_build_number(self.pbx(debug_build="8"))

    def test_bad_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "must look like"):
            ios_release.project_marketing_version(self.pbx(debug_version="$(VERSION)", release_version="$(VERSION)"))
        with self.assertRaisesRegex(ReleaseError, "whole number"):
            ios_release.project_build_number(self.pbx(debug_build="7a", release_build="7a"))

    def test_missing_app_target_fails(self) -> None:
        path = self.pbx()
        with self.assertRaisesRegex(ReleaseError, "no build configuration"):
            ios_release.app_build_configurations(path, bundle_id="com.example.other")


class BuildNumberTests(unittest.TestCase):
    def test_next_build_number(self) -> None:
        self.assertEqual(ios_release.next_build_number(2, ["1", "2"]), 3)
        self.assertEqual(ios_release.next_build_number(9, ["1", "2"]), 9)
        self.assertEqual(ios_release.next_build_number(1, []), 1)
        self.assertEqual(ios_release.next_build_number(5, ["7.1", "abc", "9"]), 10)
        self.assertEqual(ios_release.next_build_number(5, ["٩٩"]), 5)  # only ASCII digits count


STARTED = 1_800_000_000.0  # this run's upload start (epoch seconds)


def iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()


def build_row(build_id: str = "B1", *, number: str = "3", state: str = "VALID", expired: bool = False,
              uploaded: float | str | None = STARTED + 60, app: str = APP, pre: str = "P1") -> dict:
    attributes = {"version": number, "processingState": state, "expired": expired}
    if uploaded is not None:
        attributes["uploadedDate"] = uploaded if isinstance(uploaded, str) else iso(uploaded)
    return {
        "type": "builds",
        "id": build_id,
        "attributes": attributes,
        "relationships": {
            "preReleaseVersion": {"data": {"type": "preReleaseVersions", "id": pre}},
            "app": {"data": {"type": "apps", "id": app}},
        },
    }


def pre_row(pre_id: str = "P1", version: str = VERSION, platform: str = "IOS") -> dict:
    return {"type": "preReleaseVersions", "id": pre_id, "attributes": {"version": version, "platform": platform}}


class FakeClock:
    def __init__(self, start: float) -> None:
        self.time = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.time += seconds


class SequenceClient:
    """Returns queued /builds payloads (or raises queued exceptions) per GET."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.paths: list[str] = []

    def get(self, path: str) -> dict:
        self.paths.append(path)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, BaseException):
            raise item
        return item


def wait(client: SequenceClient, clock: FakeClock, *, minutes: int = 120, transient=None) -> dict:
    with redirect_stdout(io.StringIO()):
        return ios_release.wait_for_build(
            client, app_id=APP, marketing_version=VERSION, build_number="3", uploaded_after=STARTED,
            deadline=STARTED + minutes * 60, poll_seconds=30, now=clock.now, sleep=clock.sleep,
            is_transient=transient,
        )


class WaitForBuildTests(unittest.TestCase):
    def test_waits_through_missing_and_processing_then_returns_build(self) -> None:
        client = SequenceClient([
            {"data": []},
            {"data": [build_row(state="PROCESSING")], "included": [pre_row()]},
            {"data": [build_row()], "included": [pre_row()]},
        ])
        clock = FakeClock(STARTED + 120)
        self.assertEqual(wait(client, clock)["id"], "B1")
        self.assertEqual(clock.sleeps, [30, 30])
        self.assertIn("filter%5Bversion%5D=3", client.paths[0])
        self.assertIn(f"filter%5Bapp%5D={APP}", client.paths[0])

    def test_times_out_without_using_another_build(self) -> None:
        client = SequenceClient([{"data": [build_row(state="PROCESSING")], "included": [pre_row()]}])
        clock = FakeClock(STARTED)
        with self.assertRaisesRegex(ReleaseError, "timed out"):
            wait(client, clock, minutes=10)
        self.assertLessEqual(clock.time, STARTED + 10 * 60 + 30)

    def test_ready_build_after_the_deadline_is_still_a_timeout(self) -> None:
        client = SequenceClient([{"data": [build_row()], "included": [pre_row()]}])
        clock = FakeClock(STARTED + 121 * 60)
        with self.assertRaisesRegex(ReleaseError, "timed out"):
            wait(client, clock)
        self.assertEqual(client.paths, [], "must not poll once the budget is spent")

    def test_processing_failure_stops(self) -> None:
        for state in ("FAILED", "INVALID"):
            client = SequenceClient([{"data": [build_row(state=state)], "included": [pre_row()]}])
            with self.subTest(state=state), self.assertRaisesRegex(ReleaseError, state):
                wait(client, FakeClock(STARTED))

    def test_expired_build_is_rejected(self) -> None:
        client = SequenceClient([{"data": [build_row(expired=True)], "included": [pre_row()]}])
        with self.assertRaisesRegex(ReleaseError, "expired"):
            wait(client, FakeClock(STARTED))

    def test_ambiguous_match_stops(self) -> None:
        client = SequenceClient([{"data": [build_row("B1"), build_row("B2")], "included": [pre_row()]}])
        with self.assertRaisesRegex(ReleaseError, "ambiguous"):
            wait(client, FakeClock(STARTED))

    def test_older_upload_is_never_substituted(self) -> None:
        client = SequenceClient([{"data": [build_row(uploaded=STARTED - 3600)], "included": [pre_row()]}])
        with self.assertRaisesRegex(ReleaseError, "older build"):
            wait(client, FakeClock(STARTED))

    def test_build_without_an_upload_time_is_never_accepted(self) -> None:
        # Fail closed: it could be an older build with the same number.
        for missing in (None, ""):
            client = SequenceClient([{"data": [build_row(uploaded=missing)], "included": [pre_row()]}])
            with self.subTest(uploaded=missing), self.assertRaisesRegex(ReleaseError, "timed out"):
                wait(client, FakeClock(STARTED), minutes=10)
        state, message, build = ios_release.evaluate_builds(
            {"data": [build_row(uploaded=None)], "included": [pre_row()]},
            app_id=APP, marketing_version=VERSION, build_number="3", uploaded_after=STARTED)
        self.assertEqual((state, build), (ios_release.BuildState.WAITING, None))
        self.assertIn("uploadedDate", message)

    def test_upload_time_reported_later_is_accepted(self) -> None:
        client = SequenceClient([
            {"data": [build_row(uploaded=None)], "included": [pre_row()]},
            {"data": [build_row()], "included": [pre_row()]},
        ])
        clock = FakeClock(STARTED)
        self.assertEqual(wait(client, clock)["id"], "B1")
        self.assertEqual(clock.sleeps, [30])

    def test_unreadable_upload_time_stops(self) -> None:
        for bad in ("yesterday", 1_800_000_000):
            client = SequenceClient([{"data": [build_row(uploaded=None)], "included": [pre_row()]}])
            client.responses[0]["data"][0]["attributes"]["uploadedDate"] = bad
            with self.subTest(uploaded=bad), self.assertRaisesRegex(ReleaseError, "unreadable uploadedDate"):
                wait(client, FakeClock(STARTED))

    def test_other_versions_and_platforms_are_ignored(self) -> None:
        other_version = build_row("BX", pre="P2")
        other_platform = build_row("BY", pre="P3")
        client = SequenceClient([
            {"data": [other_version, other_platform], "included": [pre_row("P2", "1.0"), pre_row("P3", VERSION, "MAC_OS")]},
            {"data": [other_version, build_row("B1")], "included": [pre_row("P2", "1.0"), pre_row()]},
        ])
        self.assertEqual(wait(client, FakeClock(STARTED))["id"], "B1")

    def test_build_from_another_app_is_a_mismatch(self) -> None:
        client = SequenceClient([{"data": [build_row(app="OTHER")], "included": [pre_row()]}])
        with self.assertRaisesRegex(ReleaseError, "another app"):
            wait(client, FakeClock(STARTED))

    def test_transient_errors_are_retried_and_others_raise(self) -> None:
        transient = asc_release.AscHttpError(503, "unavailable")
        client = SequenceClient([transient, {"data": [build_row()], "included": [pre_row()]}])
        with redirect_stderr(io.StringIO()):
            build = wait(client, FakeClock(STARTED), transient=ios_release.is_transient_error)
        self.assertEqual(build["id"], "B1")
        fatal = SequenceClient([asc_release.AscHttpError(401, "unauthorized")])
        with self.assertRaises(SystemExit):
            wait(fatal, FakeClock(STARTED), transient=ios_release.is_transient_error)


class TransientErrorTests(unittest.TestCase):
    def test_retry_rule(self) -> None:
        transient = [
            http.client.RemoteDisconnected("closed"),
            ConnectionResetError("reset"),
            http.client.IncompleteRead(b""),
            urllib.error.URLError("dns"),
            TimeoutError("slow"),
            asc_release.AscHttpError(503, "busy"),
            asc_release.AscHttpError(429, "rate limited"),
            urllib.error.HTTPError("https://x", 502, "bad gateway", {}, None),
        ]
        fatal = [
            asc_release.AscHttpError(401, "unauthorized"),
            asc_release.AscHttpError(409, "conflict"),
            urllib.error.HTTPError("https://x", 404, "missing", {}, None),
            ValueError("bad"),
            ReleaseError("mismatch"),
            SystemExit(1),
        ]
        for exc in transient:
            with self.subTest(exc=repr(exc)):
                self.assertTrue(ios_release.is_transient_error(exc))
        for exc in fatal:
            with self.subTest(exc=repr(exc)):
                self.assertFalse(ios_release.is_transient_error(exc))


class CmdWaitBuildTests(unittest.TestCase):
    def test_deadline_counts_from_upload_start_and_app_lookup_is_retried(self) -> None:
        lookups = []

        def find_app(_client, bundle_id):
            lookups.append(bundle_id)
            if len(lookups) == 1:
                raise http.client.RemoteDisconnected("closed")
            return APP

        captured = {}

        def fake_wait(client, **kwargs):
            captured.update(kwargs)
            return {"id": "B9"}

        args = argparse.Namespace(version=VERSION, build=3, started_at=STARTED, wait_minutes=120, poll_seconds=30)
        with tempfile.NamedTemporaryFile("r", suffix=".out") as out, \
                mock.patch.object(ios_release, "asc_client", return_value=(mock.Mock(find_app=find_app), object())), \
                mock.patch.object(ios_release, "wait_for_build", side_effect=fake_wait), \
                mock.patch.object(ios_release.time, "sleep"), \
                mock.patch.object(ios_release.time, "time", return_value=STARTED + 30), \
                mock.patch.dict(os.environ, {"GITHUB_OUTPUT": out.name}), redirect_stdout(io.StringIO()):
            ios_release.cmd_wait_build(args)
            written = Path(out.name).read_text()
        self.assertEqual(lookups, [ios_release.BUNDLE_ID] * 2)
        self.assertEqual(captured["deadline"], STARTED + 120 * 60)
        self.assertEqual(captured["uploaded_after"], STARTED)
        self.assertEqual(captured["build_number"], "3")
        self.assertIs(captured["is_transient"], ios_release.is_transient_error)
        self.assertIn("build_id=B9", written)

    def test_app_lookup_gives_up_at_the_deadline(self) -> None:
        def boom():
            raise http.client.RemoteDisconnected("closed")

        clock = FakeClock(STARTED)
        with redirect_stdout(io.StringIO()), self.assertRaises(http.client.RemoteDisconnected):
            ios_release.call_with_retries(boom, deadline=STARTED + 90, poll_seconds=30, now=clock.now, sleep=clock.sleep)
        self.assertEqual(clock.sleeps, [30, 30, 30])


class CmdBuildNumberTests(unittest.TestCase):
    def test_uses_the_highest_uploaded_build_plus_one(self) -> None:
        client = mock.Mock()
        client.get.side_effect = [
            {"data": [{"id": APP, "attributes": {"bundleId": ios_release.BUNDLE_ID}}]},
            {"data": [{"attributes": {"version": "1"}}, {"attributes": {"version": "2"}}],
             "links": {"next": "https://api.appstoreconnect.apple.com/v1/builds?cursor=2"}},
            {"data": [{"attributes": {"version": "5"}}]},
        ]
        with tempfile.NamedTemporaryFile("r", suffix=".out") as out, \
                mock.patch.object(ios_release, "asc_client", return_value=(asc_release, client)), \
                mock.patch.object(ios_release, "project_build_number", return_value=2), \
                mock.patch.dict(os.environ, {"GITHUB_OUTPUT": out.name}), redirect_stdout(io.StringIO()):
            ios_release.cmd_build_number(argparse.Namespace())
            self.assertIn("build_number=6", Path(out.name).read_text())


class FindAppTests(unittest.TestCase):
    def client(self, rows: list[dict]) -> mock.Mock:
        client = mock.Mock()
        client.get.return_value = {"data": rows}
        return client

    def test_returns_abysm_only(self) -> None:
        row = {"id": APP, "attributes": {"bundleId": asc_release.DEFAULT_BUNDLE_ID}}
        self.assertEqual(asc_release.find_app(self.client([row]), asc_release.DEFAULT_BUNDLE_ID), APP)

    def test_wrong_missing_or_ambiguous_app_fails(self) -> None:
        row = {"id": APP, "attributes": {"bundleId": asc_release.DEFAULT_BUNDLE_ID}}
        cases = {
            "other id": [{"id": "999", "attributes": {"bundleId": asc_release.DEFAULT_BUNDLE_ID}}],
            "missing": [],
            "prefix only": [{"id": APP, "attributes": {"bundleId": asc_release.DEFAULT_BUNDLE_ID + ".beta"}}],
            "ambiguous": [row, dict(row)],
            "two apps with the bundle id": [row, {"id": "999", "attributes": {"bundleId": asc_release.DEFAULT_BUNDLE_ID}}],
            "no bundle id reported": [{"id": APP}],
        }
        for label, rows in cases.items():
            with self.subTest(label), self.assertRaises(SystemExit):
                quiet(asc_release.find_app, self.client(rows), asc_release.DEFAULT_BUNDLE_ID)


class SelectionClient:
    """Fake ASC client for build verification and selection."""

    def __init__(self, *, build: dict, included: list, attached: str | None, sticky: bool = True) -> None:
        self.build = build
        self.included = included
        self.attached = attached
        self.sticky = sticky
        self.calls: list[tuple[str, str, dict | None]] = []

    def get(self, path: str) -> dict:
        self.calls.append(("GET", path, None))
        if path.startswith(f"/builds/{self.build['id']}"):
            return {"data": self.build, "included": self.included}
        if path.endswith("/build"):
            return {"data": {"type": "builds", "id": self.attached} if self.attached else None}
        raise AssertionError(f"unexpected GET {path}")

    def patch(self, path: str, body: dict) -> dict:
        self.calls.append(("PATCH", path, body))
        return {"data": body["data"]}

    def request(self, method: str, path: str, body: dict | None = None):
        self.calls.append((method, path, body))
        if method == "PATCH" and path.endswith("/relationships/build") and self.sticky:
            self.attached = body["data"]["id"]
        return None


class BuildSelectionTests(unittest.TestCase):
    def test_selects_and_reads_back_this_runs_build(self) -> None:
        client = SelectionClient(build=build_row("B9"), included=[pre_row()], attached="OLD")
        quiet(asc_release.select_build, client, "V1", "B9", VERSION, "3")
        self.assertEqual(client.attached, "B9")
        methods = [(m, p) for m, p, _ in client.calls]
        self.assertIn(("PATCH", "/appStoreVersions/V1/relationships/build"), methods)
        self.assertEqual(methods[-1], ("GET", "/appStoreVersions/V1/build"))

    def test_selection_that_does_not_stick_fails(self) -> None:
        client = SelectionClient(build=build_row("B9"), included=[pre_row()], attached="OLD", sticky=False)
        with self.assertRaises(SystemExit):
            quiet(asc_release.select_build, client, "V1", "B9", VERSION, "3")

    def test_unprocessed_expired_or_wrong_build_is_refused(self) -> None:
        cases = {
            "processing": (build_row("B9", state="PROCESSING"), [pre_row()]),
            "expired": (build_row("B9", expired=True), [pre_row()]),
            "number": (build_row("B9", number="4"), [pre_row()]),
            "version": (build_row("B9"), [pre_row(version="1.0")]),
            "platform": (build_row("B9"), [pre_row(platform="TV_OS")]),
        }
        for label, (build, included) in cases.items():
            client = SelectionClient(build=build, included=included, attached=None)
            with self.subTest(label), self.assertRaises(SystemExit):
                quiet(asc_release.select_build, client, "V1", "B9", VERSION, "3")
            self.assertFalse([c for c in client.calls if c[0] == "PATCH"], label)

    def test_release_type(self) -> None:
        for public, expected in ((True, "AFTER_APPROVAL"), (False, "MANUAL")):
            client = SelectionClient(build=build_row(), included=[], attached=None)
            quiet(asc_release.set_release_type, client, "V1", public_release=public)
            self.assertEqual(client.calls[-1][2]["data"]["attributes"]["releaseType"], expected)


class TokenRefreshTests(unittest.TestCase):
    def test_token_is_reminted_during_long_waits(self) -> None:
        minted: list[str] = []

        def factory() -> str:
            minted.append(f"t{len(minted)}")
            return minted[-1]

        with mock.patch.object(asc_release.time, "monotonic", side_effect=[0, 100, 700, 700, 800]):
            client = asc_release.AscClient(token_factory=factory)
            self.assertEqual(client._authorization(), "Bearer t0")
            self.assertEqual(client._authorization(), "Bearer t1")
            self.assertEqual(client._authorization(), "Bearer t1")

    def test_client_needs_a_token_source(self) -> None:
        with self.assertRaises(ValueError):
            asc_release.AscClient()


def png(path: Path, width: int, height: int) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR"
                     + width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x06\x00\x00\x00")
    return path


class ScreenshotPlanTests(unittest.TestCase):
    def sets(self, folder: Path) -> tuple:
        return (("APP_IPHONE_67", folder, frozenset({(2796, 1290)})),)

    @repo_content
    def test_repo_marketing_images_are_app_store_ready(self) -> None:
        plan = asc_release.screenshot_plan()
        self.assertEqual([display for display, _ in plan], ["APP_IPHONE_67", "APP_IPAD_PRO_3GEN_129"])
        for display, files in plan:
            self.assertGreaterEqual(len(files), 1, display)
            self.assertLessEqual(len(files), asc_release.APP_SCREENSHOT_SET_MAX, display)
            self.assertEqual(files, sorted(files), "uploads keep file-name order")

    def test_missing_or_empty_folder_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for folder in (Path(tmp) / "missing", Path(tmp)):
                with self.subTest(folder=folder.name), self.assertRaises(SystemExit) as ctx:
                    err = io.StringIO()
                    with redirect_stderr(err):
                        asc_release.screenshot_plan(self.sets(folder))
                self.assertIn("IOS_UPLOAD_SCREENSHOTS", err.getvalue())

    def test_wrong_size_or_non_png_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            png(Path(tmp) / "01.png", 2796, 1290)
            png(Path(tmp) / "02.png", 1179, 2556)
            with self.assertRaises(SystemExit):
                quiet(asc_release.screenshot_plan, self.sets(Path(tmp)))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "01.png").write_bytes(b"GIF89a not a png at all......")
            with self.assertRaises(SystemExit):
                quiet(asc_release.screenshot_plan, self.sets(Path(tmp)))

    def test_too_many_files_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(asc_release.APP_SCREENSHOT_SET_MAX + 1):
                png(Path(tmp) / f"{i:02}.png", 2796, 1290)
            with self.assertRaises(SystemExit):
                quiet(asc_release.screenshot_plan, self.sets(Path(tmp)))

    def test_accepted_sizes_pass_in_name_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            png(Path(tmp) / "02-b.png", 2796, 1290)
            png(Path(tmp) / "01-a.png", 2796, 1290)
            plan = asc_release.screenshot_plan(self.sets(Path(tmp)))
            self.assertEqual([p.name for p in plan[0][1]], ["01-a.png", "02-b.png"])


class ScreenshotUploadClient:
    """Screenshot sets with a capacity, asset uploads and processing states.

    `delivered` is the assetDeliveryState of each screenshot already in the set
    (COMPLETE unless given; None leaves the state out). `states` are what the
    run's wait reads from GET /appScreenshots/{id}, in order (the last repeats).
    Like App Store Connect, a commit stores the checksum at once, before the
    image is processed.
    """

    def __init__(self, existing: int, *, states: list[str] | None = None, checksums: list[str] | None = None,
                 delivered: list[str | None] | None = None) -> None:
        self.shots = [f"OLD{i}" for i in range(existing)]
        self.checksums = dict(zip(self.shots, checksums or []))
        self.delivery: dict[str, str | None] = dict(
            zip(self.shots, delivered if delivered is not None else ["COMPLETE"] * existing))
        self.states = states or ["COMPLETE"]
        self.calls: list[tuple[str, str]] = []
        self.commits: list[dict] = []
        self.uploads = 0

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] != "GET"]

    def listed(self, shot_id: str) -> dict:
        attributes: dict = {"fileName": f"{shot_id}.png", "sourceFileChecksum": self.checksums.get(shot_id)}
        if self.delivery.get(shot_id) is not None:
            attributes["assetDeliveryState"] = {"state": self.delivery[shot_id], "errors": []}
        return {"id": shot_id, "attributes": attributes}

    def get(self, path: str) -> dict:
        self.calls.append(("GET", path))
        if "/appStoreVersionLocalizations" in path and path.startswith("/appStoreVersions/"):
            return {"data": [{"id": "LOC", "attributes": {"locale": "en-US"}}]}
        if path.endswith("/appScreenshotSets") or "/appScreenshotSets?" in path:
            return {"data": [{"id": "SET", "attributes": {"screenshotDisplayType": "APP_IPHONE_67"}}]}
        if "/appScreenshotSets/SET/appScreenshots" in path:
            return {"data": [self.listed(s) for s in self.shots]}
        if path.startswith("/appScreenshots/"):
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            self.delivery[path.rsplit("/", 1)[1]] = state
            return {"data": {"attributes": {"fileName": "x.png", "assetDeliveryState": {
                "state": state, "errors": [{"description": "bad image"}] if state == "FAILED" else []}}}}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, body: dict) -> dict:
        self.calls.append(("POST", path))
        assert path == "/appScreenshots"
        assert len(self.shots) < asc_release.APP_SCREENSHOT_SET_MAX, "reservation while the set is full"
        new_id = f"NEW{len(self.shots)}-{self.uploads}"
        self.uploads += 1
        self.shots.append(new_id)
        self.delivery[new_id] = "AWAITING_UPLOAD"
        return {"data": {"id": new_id, "attributes": {"uploadOperations": [
            {"url": "https://upload.example/x", "offset": 0, "length": body["data"]["attributes"]["fileSize"],
             "method": "PUT", "requestHeaders": [{"name": "Content-Type", "value": "image/png"}]}]}}}

    def patch(self, path: str, body: dict) -> dict:
        self.calls.append(("PATCH", path))
        attributes = body["data"]["attributes"]
        self.commits.append(attributes)
        shot_id = path.rsplit("/", 1)[1]
        self.checksums[shot_id] = attributes.get("sourceFileChecksum")
        self.delivery[shot_id] = "UPLOAD_COMPLETE"
        return {"data": body["data"]}

    def request(self, method: str, path: str, body: dict | None = None):
        self.calls.append((method, path))
        if method == "DELETE":
            self.shots.remove(path.rsplit("/", 1)[1])

    def upload_bytes(self, url: str, data: bytes, headers: dict, *, method: str = "PUT") -> None:
        self.calls.append(("UPLOAD", url))


class ScreenshotUploadTests(unittest.TestCase):
    def plan(self, tmp: str, count: int) -> list:
        files = [png(Path(tmp) / f"{i:02}.png", 2796, 1290) for i in range(count)]
        for i, path in enumerate(files):  # distinct contents, so each file has its own checksum
            path.write_bytes(path.read_bytes() + bytes([i]))
        return [("APP_IPHONE_67", files)]

    def test_replaces_a_full_set_without_exceeding_capacity(self) -> None:
        client = ScreenshotUploadClient(existing=10)
        with tempfile.TemporaryDirectory() as tmp:
            quiet(asc_release.upload_screenshots, client, version_id="V1", locale="en-US",
                  plan=self.plan(tmp, 5), wait=lambda c, ids: None)
        self.assertEqual(len(client.shots), 5)
        self.assertTrue(all(s.startswith("NEW") for s in client.shots), client.shots)
        self.assertTrue(all(c["uploaded"] is True and len(c["sourceFileChecksum"]) == 32 for c in client.commits))

    def test_a_set_that_already_matches_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.plan(tmp, 3)
            same = [asc_release.md5_hex(p) for p in plan[0][1]]
            for editable in (True, False):
                client = ScreenshotUploadClient(existing=3, checksums=same)
                differing = quiet(asc_release.upload_screenshots, client, version_id="V1", locale="en-US",
                                  plan=plan, wait=lambda c, ids: None, editable=editable, state="READY_FOR_REVIEW")
                self.assertEqual((differing, client.writes()), ([], []), editable)
            # Same images in another order still differ.
            client = ScreenshotUploadClient(existing=3, checksums=list(reversed(same)))
            self.assertEqual(quiet(asc_release.upload_screenshots, client, version_id="V1", locale="en-US",
                                   plan=plan, wait=lambda c, ids: None), ["APP_IPHONE_67"])

    def test_locked_or_read_only_runs_never_change_screenshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.plan(tmp, 2)
            locked = ScreenshotUploadClient(existing=2, checksums=["old", "old"])
            err = io.StringIO()
            with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), redirect_stderr(err):
                asc_release.upload_screenshots(locked, version_id="V1", locale="en-US", plan=plan,
                                               wait=lambda c, ids: None, editable=False, state="READY_FOR_REVIEW")
            self.assertIn("READY_FOR_REVIEW", err.getvalue())
            self.assertEqual(locked.writes(), [])
            preview = ScreenshotUploadClient(existing=2)
            differing = quiet(asc_release.upload_screenshots, preview, version_id="V1", locale="en-US", plan=plan,
                              wait=lambda c, ids: None, write=False)
            self.assertEqual((differing, preview.writes()), (["APP_IPHONE_67"], []))

    def test_waits_for_processing_and_fails_on_rejection(self) -> None:
        clock = FakeClock(0)
        client = ScreenshotUploadClient(existing=0, states=["UPLOAD_COMPLETE", "COMPLETE"])
        quiet(asc_release.wait_for_screenshots, client, ["S1"], timeout=60, poll_seconds=5,
              now=clock.now, sleep=clock.sleep)
        self.assertEqual(clock.sleeps, [5])
        failed = ScreenshotUploadClient(existing=0, states=["FAILED"])
        with self.assertRaises(SystemExit):
            quiet(asc_release.wait_for_screenshots, failed, ["S1"], timeout=60, poll_seconds=5,
                  now=clock.now, sleep=clock.sleep)
        stuck = ScreenshotUploadClient(existing=0, states=["UPLOAD_COMPLETE"])
        clock = FakeClock(0)
        with self.assertRaises(SystemExit):
            quiet(asc_release.wait_for_screenshots, stuck, ["S1"], timeout=20, poll_seconds=5,
                  now=clock.now, sleep=clock.sleep)
        self.assertEqual(clock.time, 20)

    def test_the_repo_images_count_as_uploaded_only_once_apple_has_processed_them(self) -> None:
        # The commit stores sourceFileChecksum before Apple processes the image, so a set
        # left by a failed or timed-out wait already holds the repo's checksums.
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.plan(tmp, 3)
            same = [asc_release.md5_hex(p) for p in plan[0][1]]
            for unfinished in ("FAILED", "UPLOAD_COMPLETE", "AWAITING_UPLOAD", None):
                delivered = ["COMPLETE", unfinished, "COMPLETE"]
                with self.subTest(state=unfinished):
                    # Editable: the whole set is uploaded again, and the new images are waited for.
                    client = ScreenshotUploadClient(existing=3, checksums=same, delivered=delivered)
                    waited: list[str] = []
                    differing = quiet(asc_release.upload_screenshots, client, version_id="V1", locale="en-US",
                                      plan=plan, wait=lambda c, ids: waited.extend(ids))
                    self.assertEqual(differing, ["APP_IPHONE_67"])
                    self.assertEqual(waited, client.shots)
                    self.assertFalse({"OLD0", "OLD1", "OLD2"} & set(client.shots), client.shots)
                    # Locked: fails without a write and names the unfinished image.
                    locked = ScreenshotUploadClient(existing=3, checksums=same, delivered=delivered)
                    err = io.StringIO()
                    with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), redirect_stderr(err):
                        asc_release.upload_screenshots(locked, version_id="V1", locale="en-US", plan=plan,
                                                       wait=lambda c, ids: None, editable=False, state="IN_REVIEW")
                    self.assertIn(f"OLD1.png: {unfinished or 'no processing state'}", err.getvalue())
                    self.assertIn("screenshots cannot change while the version is IN_REVIEW", err.getvalue())
                    self.assertEqual(locked.writes(), [])
                    # Preflight: reported, nothing sent.
                    preview = ScreenshotUploadClient(existing=3, checksums=same, delivered=delivered)
                    out = io.StringIO()
                    with redirect_stdout(out), redirect_stderr(io.StringIO()):
                        differing = asc_release.upload_screenshots(preview, version_id="V1", locale="en-US",
                                                                   plan=plan, wait=lambda c, ids: None, write=False)
                    self.assertEqual((differing, preview.writes()), (["APP_IPHONE_67"], []))
                    self.assertIn("would replace", out.getvalue())

    def test_a_rerun_repairs_a_set_left_by_a_failed_or_timed_out_wait(self) -> None:
        # Apple rejects an image, or is still processing it at the deadline; then
        # "Re-run failed jobs" must upload the set again, not take it as done.
        for outcome in ("FAILED", "UPLOAD_COMPLETE"):
            with self.subTest(first_attempt=outcome), tempfile.TemporaryDirectory() as tmp:
                plan = self.plan(tmp, 2)
                clock = FakeClock(0)

                def run(client: ScreenshotUploadClient) -> list[str]:
                    return quiet(asc_release.upload_screenshots, client, version_id="V1", locale="en-US", plan=plan,
                                 wait=lambda c, ids: asc_release.wait_for_screenshots(
                                     c, ids, timeout=20, poll_seconds=5, now=clock.now, sleep=clock.sleep))

                client = ScreenshotUploadClient(existing=2, states=[outcome])
                with self.assertRaises(SystemExit):
                    run(client)
                first = list(client.shots)
                self.assertEqual([client.checksums[s] for s in first], [asc_release.md5_hex(p) for p in plan[0][1]])
                client.states = ["COMPLETE"]  # this time Apple processes the images
                self.assertEqual(run(client), ["APP_IPHONE_67"])
                self.assertTrue(set(first).isdisjoint(client.shots), client.shots)
                self.assertEqual([client.delivery[s] for s in client.shots], ["COMPLETE", "COMPLETE"])
                # Once the set is done, a further re-run sends nothing.
                writes = len(client.writes())
                self.assertEqual(run(client), [])
                self.assertEqual(len(client.writes()), writes)


def metadata_tree(tmp: str, files: dict[str, str], locale: str = "en-US") -> Path:
    loc = Path(tmp) / "ios" / locale
    loc.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (loc / name).write_text(text)
    return Path(tmp)


class ListingTests(unittest.TestCase):
    @repo_content
    def test_repo_metadata_is_valid_for_every_switch_but_whats_new(self) -> None:
        locales, _ = asc_release.validate_local_inputs(
            upload_listing=True, upload_whats_new=False, upload_screenshots=False,
            metadata_dir=asc_release.METADATA_DIR)
        self.assertIn(asc_release.PRIMARY_LOCALE, locales)

    def test_limits_and_urls_are_enforced(self) -> None:
        cases = {
            "keywords": {"description.txt": "D", "keywords.txt": "k" * 101},
            "description": {"description.txt": "D" * 4001, "keywords.txt": "k"},
            "promo": {"description.txt": "D", "keywords.txt": "k", "promotional_text.txt": "p" * 171},
            "url": {"description.txt": "D", "keywords.txt": "k", "support_url.txt": "http://insecure.example"},
            "name": {"description.txt": "D", "keywords.txt": "k", "name.txt": "n" * 31},
            "missing description": {"keywords.txt": "k"},
        }
        for label, files in cases.items():
            with tempfile.TemporaryDirectory() as tmp, self.subTest(label), self.assertRaises(SystemExit):
                quiet(asc_release.validate_local_inputs, upload_listing=True, upload_whats_new=False,
                      upload_screenshots=False, metadata_dir=metadata_tree(tmp, files))

    def test_whats_new_needs_text_in_every_locale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = metadata_tree(tmp, {"whats_new.txt": "Fixes"})
            metadata_tree(tmp, {"description.txt": "D"}, locale="de-DE")
            with self.assertRaises(SystemExit):
                quiet(asc_release.validate_local_inputs, upload_listing=False, upload_whats_new=True,
                      upload_screenshots=False, metadata_dir=meta)
            (meta / "ios" / "de-DE" / "whats_new.txt").write_text("Fehlerbehebungen")
            locales, _ = asc_release.validate_local_inputs(
                upload_listing=False, upload_whats_new=True, upload_screenshots=False, metadata_dir=meta)
            self.assertEqual(locales, ["de-DE", "en-US"])

    def listing_client(self, version_attrs: dict, info_attrs: dict | None = None, *, editable: bool = True) -> mock.Mock:
        client = mock.Mock()

        def get(path: str) -> dict:
            if path.startswith("/appStoreVersions/V1/appStoreVersionLocalizations"):
                return {"data": [{"id": "LOC", "attributes": {"locale": "en-US", **version_attrs}}]}
            if path.startswith(f"/apps/{APP}/appInfos"):
                state = "PREPARE_FOR_SUBMISSION" if editable else "READY_FOR_SALE"
                return {"data": [{"id": "INFO", "attributes": {"appStoreState": state}}]}
            if path.startswith("/appInfos/INFO/appInfoLocalizations"):
                return {"data": [{"id": "ILOC", "attributes": {"locale": "en-US", **(info_attrs or {})}}]}
            raise AssertionError(path)

        client.get.side_effect = get
        client.patch.return_value = {"data": {}}
        return client

    def upload(self, client, files: dict, *, listing=True, whats_new=False) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quiet(asc_release.upload_listing, client, app_id=APP, version_id="V1", locale="en-US",
                  metadata_dir=metadata_tree(tmp, files), include_listing=listing, include_whats_new=whats_new)

    def test_only_changed_fields_are_sent_and_whats_new_has_its_own_switch(self) -> None:
        files = {"description.txt": "New desc\n", "keywords.txt": "same", "whats_new.txt": "Fixes"}
        client = self.listing_client({"description": "Old desc", "keywords": "same"})
        self.upload(client, files)
        version_patch = client.patch.call_args_list[0]
        self.assertEqual(version_patch.args[0], "/appStoreVersionLocalizations/LOC")
        self.assertEqual(version_patch.args[1]["data"]["attributes"], {"description": "New desc"})
        client = self.listing_client({"description": "New desc", "keywords": "same"})
        self.upload(client, files, listing=False, whats_new=True)
        self.assertEqual(client.patch.call_args.args[1]["data"]["attributes"], {"whatsNew": "Fixes"})
        client = self.listing_client({"description": "New desc", "keywords": "same", "whatsNew": "Fixes"})
        self.upload(client, files, listing=True, whats_new=True)
        client.patch.assert_not_called()

    def test_app_info_is_updated_only_while_editable(self) -> None:
        files = {"description.txt": "D", "keywords.txt": "k", "subtitle.txt": "A new subtitle"}
        client = self.listing_client({"description": "D", "keywords": "k"}, {"subtitle": "Old"})
        self.upload(client, files)
        self.assertEqual(client.patch.call_args.args[0], "/appInfoLocalizations/ILOC")
        self.assertEqual(client.patch.call_args.args[1]["data"]["attributes"], {"subtitle": "A new subtitle"})
        locked = self.listing_client({"description": "D", "keywords": "k"}, {"subtitle": "Old"}, editable=False)
        with self.assertRaises(SystemExit):
            self.upload(locked, files)
        same = self.listing_client({"description": "D", "keywords": "k"}, {"subtitle": "A new subtitle"}, editable=False)
        self.upload(same, files)
        same.patch.assert_not_called()

    def test_missing_localization_fails(self) -> None:
        client = mock.Mock()
        client.get.return_value = {"data": [{"id": "LOC", "attributes": {"locale": "fr-FR"}}]}
        with self.assertRaises(SystemExit):
            self.upload(client, {"description.txt": "D"})

    def sync(self, client, files: dict, **kwargs) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            return quiet(asc_release.upload_listing, client, app_id=APP, version_id="V1", locale="en-US",
                         metadata_dir=metadata_tree(tmp, files), **kwargs)

    def test_locked_text_is_compared_never_changed(self) -> None:
        # WAITING_FOR_REVIEW / IN_REVIEW: a re-run passes only when nothing would change.
        files = {"description.txt": "D", "keywords.txt": "k", "whats_new.txt": "Fixes", "subtitle.txt": "Sub"}
        locked = {"text_editable": False, "include_whats_new": True, "state": "WAITING_FOR_REVIEW"}
        same = self.listing_client({"description": "D", "keywords": "k", "whatsNew": "Fixes"}, {"subtitle": "Sub"},
                                   editable=False)
        self.assertEqual(self.sync(same, files, **locked), [])
        same.patch.assert_not_called()
        for version_attrs, info_attrs in (({"description": "Old", "keywords": "k", "whatsNew": "Fixes"}, {"subtitle": "Sub"}),
                                          ({"description": "D", "keywords": "k", "whatsNew": "Fixes"}, {"subtitle": "Old"})):
            differs = self.listing_client(version_attrs, info_attrs, editable=False)
            with self.subTest(version=version_attrs, info=info_attrs), self.assertRaises(SystemExit):
                self.sync(differs, files, **locked)
            differs.patch.assert_not_called()

    def test_read_only_run_reports_changes_without_sending_them(self) -> None:
        files = {"description.txt": "New", "keywords.txt": "k", "subtitle.txt": "New sub"}
        client = self.listing_client({"description": "Old", "keywords": "k"}, {"subtitle": "Old"})
        self.assertEqual(self.sync(client, files, write=False), ["en-US description", "en-US subtitle"])
        client.patch.assert_not_called()

    def test_app_info_of_the_version_in_review_is_compared_not_the_live_one(self) -> None:
        client = mock.Mock()
        locs = {"LIVE": "Live subtitle", "NEXT": "Next subtitle"}

        def get(path: str) -> dict:
            if path.startswith("/appStoreVersions/V1/appStoreVersionLocalizations"):
                return {"data": [{"id": "LOC", "attributes": {"locale": "en-US", "description": "D", "keywords": "k"}}]}
            if path.startswith(f"/apps/{APP}/appInfos"):
                return {"data": [{"id": "LIVE", "attributes": {"appStoreState": "READY_FOR_SALE"}},
                                 {"id": "NEXT", "attributes": {"appStoreState": "WAITING_FOR_REVIEW"}}]}
            for info_id, subtitle in locs.items():
                if path.startswith(f"/appInfos/{info_id}/appInfoLocalizations"):
                    return {"data": [{"id": f"L-{info_id}", "attributes": {"locale": "en-US", "subtitle": subtitle}}]}
            raise AssertionError(path)

        client.get.side_effect = get
        self.assertEqual(asc_release.choose_app_info(client, APP)[0]["id"], "NEXT")
        files = {"description.txt": "D", "keywords.txt": "k", "subtitle.txt": "Next subtitle"}
        self.assertEqual(self.sync(client, files, text_editable=False, state="WAITING_FOR_REVIEW"), [])
        client.patch.assert_not_called()

    def test_ready_for_review_text_and_app_info_stay_editable(self) -> None:
        self.assertIn("READY_FOR_REVIEW", asc_release.TEXT_EDITABLE_VERSION_STATES)
        self.assertIn("READY_FOR_REVIEW", asc_release.EDITABLE_APP_INFO_STATES)
        self.assertNotIn("READY_FOR_REVIEW", asc_release.EDITABLE_VERSION_STATES)  # screenshots are locked


class ProductClient:
    """Review submissions, subscription/IAP versions and product states for product attachment."""

    def __init__(self, collections: dict[str, list[dict]]) -> None:
        self.collections = collections
        self.posts: list[tuple[str, dict]] = []
        self.requests: list[tuple[str, str, dict | None]] = []

    def get(self, path: str) -> dict:
        return {"data": self.collections.get(path, [])}

    def post(self, path: str, body: dict) -> dict:
        self.posts.append((path, body))
        return {"data": {"id": "NEW"}}

    def patch(self, path: str, body: dict) -> dict:
        raise AssertionError(f"unexpected PATCH {path}")

    def request(self, method: str, path: str, body: dict | None = None):
        self.requests.append((method, path, body))
        return None


UNLOCK = "com.apoorvdarshan.Abysm.unlockdeep"
ITEMS = asc_release.draft_items_path("SUB1")


def product_collections(unlock_state: str = "READY_TO_SUBMIT", *, draft: bool = True) -> dict[str, list[dict]]:
    return {
        asc_release.draft_submission_query(APP): [{"id": "SUB1"}] if draft else [],
        f"/apps/{APP}/subscriptionGroups?limit=200": [{"id": "G1"}],
        "/subscriptionGroups/G1/subscriptions?limit=200": [
            {"id": "S1", "attributes": {"name": "Deep Pass", "productId": "com.apoorvdarshan.Abysm.pass",
                                        "state": "DEVELOPER_REJECTED"}},
            {"id": "SX", "attributes": {"name": "Legacy", "productId": "com.apoorvdarshan.Abysm.legacy",
                                        "state": "READY_TO_SUBMIT"}},
        ],
        "/subscriptions/S1/versions": [
            {"id": "V1b", "attributes": {"version": 2}},
            {"id": "V1a", "attributes": {"version": 1}},
        ],
        f"/apps/{APP}/inAppPurchasesV2?limit=200": [
            {"id": "IAP1", "attributes": {"name": "Unlock the Deep", "productId": UNLOCK, "state": unlock_state}},
            {"id": "IAP2", "attributes": {"name": "Other", "productId": "com.apoorvdarshan.Abysm.other",
                                          "state": "READY_TO_SUBMIT"}},
        ],
        # In-app purchase versions are a v2 resource (absolute URL).
        asc_release.iap_versions_path("IAP1"): [
            {"id": "IV1", "attributes": {"version": 1, "state": "APPROVED"}},
            {"id": "IV2", "attributes": {"version": 2, "state": "PREPARE_FOR_SUBMISSION"}},
        ],
    }


def item_targets(posts: list[tuple[str, dict]]) -> list[tuple[str, str]]:
    """(relationship, id) of every review submission item posted, besides the submission itself."""
    targets = []
    for path, body in posts:
        if path == "/reviewSubmissionItems":
            for name, rel in body["data"]["relationships"].items():
                if name != "reviewSubmission":
                    targets.append((name, rel["data"]["id"]))
    return targets


class ProductAttachTests(unittest.TestCase):
    INTENDED = {UNLOCK, "com.apoorvdarshan.Abysm.pass"}

    def test_ready_catalog_products_join_the_draft_and_nothing_is_submitted(self) -> None:
        client = ProductClient(product_collections())
        result = quiet(asc_release.attach_catalog_products, client, APP, intended_ids=self.INTENDED)
        self.assertEqual((result.attached, result.added_items, result.submission_id), (2, True, "SUB1"))
        # The newest version of each product becomes an item of the same draft as the app.
        self.assertEqual(item_targets(client.posts), [("subscriptionVersion", "V1b"), ("inAppPurchaseVersion", "IV2")])
        iap_item = [b for p, b in client.posts if p == "/reviewSubmissionItems"][1]["data"]["relationships"]
        self.assertEqual(iap_item["inAppPurchaseVersion"]["data"]["type"], "inAppPurchaseVersions")
        self.assertEqual(iap_item["reviewSubmission"]["data"]["id"], "SUB1")
        # Never the deprecated standalone endpoint, never a submit.
        self.assertNotIn("/inAppPurchaseSubmissions", [p for p, _ in client.posts])
        self.assertEqual(client.requests, [])

    def test_approved_unlock_is_never_resubmitted(self) -> None:
        client = ProductClient(product_collections(unlock_state="APPROVED"))
        result = quiet(asc_release.attach_catalog_products, client, APP, intended_ids={UNLOCK})
        self.assertEqual(result.attached, 0)
        self.assertEqual(client.posts, [])

    def test_retry_skips_products_already_in_the_draft(self) -> None:
        collections = product_collections()
        collections[ITEMS] = [
            {"id": "I1", "relationships": {"subscriptionVersion": {"data": {"id": "V1b"}}}},
            {"id": "I2", "relationships": {"inAppPurchaseVersion": {"data": {"id": "IV2"}}}},
        ]
        client = ProductClient(collections)
        result = quiet(asc_release.attach_catalog_products, client, APP, intended_ids=self.INTENDED)
        self.assertEqual((result.attached, result.added_items), (2, False))
        self.assertEqual(client.posts, [])

    def test_draft_items_include_in_app_purchase_versions(self) -> None:
        self.assertIn("inAppPurchaseVersion", asc_release.draft_items_path("SUB1"))

    def test_failed_or_versionless_required_product_raises(self) -> None:
        client = ProductClient(product_collections())
        client.post = mock.Mock(side_effect=asc_release.AscHttpError(409, "conflict"))
        with self.assertRaises(asc_release.ProductSubmitError):
            quiet(asc_release.attach_catalog_products, client, APP, intended_ids={UNLOCK})
        collections = product_collections()
        collections[asc_release.iap_versions_path("IAP1")] = []
        client = ProductClient(collections)
        with self.assertRaisesRegex(asc_release.ProductSubmitError, "no version to submit"):
            quiet(asc_release.attach_catalog_products, client, APP, intended_ids={UNLOCK})
        self.assertEqual(client.posts, [])

    def test_a_draft_is_created_only_when_something_needs_one(self) -> None:
        idle = ProductClient(product_collections(unlock_state="APPROVED", draft=False))
        result = quiet(asc_release.attach_catalog_products, idle, APP, intended_ids={UNLOCK})
        self.assertEqual((result.attached, result.submission_id, idle.posts), (0, "", []))
        busy = ProductClient(product_collections(draft=False))
        result = quiet(asc_release.attach_catalog_products, busy, APP, intended_ids={UNLOCK})
        self.assertEqual([p for p, _ in busy.posts], ["/reviewSubmissions", "/reviewSubmissionItems"])
        self.assertEqual(result.submission_id, "NEW")

    def test_empty_catalog_submits_nothing(self) -> None:
        client = ProductClient(product_collections())
        result = quiet(asc_release.attach_catalog_products, client, APP, intended_ids=set())
        self.assertEqual(result.attached, 0)
        self.assertEqual(client.posts, [])

    def test_submit_for_review_does_not_add_the_version_twice(self) -> None:
        collections = {ITEMS: [{"id": "I1", "relationships": {"appStoreVersion": {"data": {"id": "AV1"}}}}]}
        client = ProductClient(collections)
        quiet(asc_release.submit_for_review, client, APP, "AV1", "PREPARE_FOR_SUBMISSION", submission_id="SUB1")
        self.assertEqual([p for p, _ in client.posts], [])
        self.assertIn(("PATCH", "/reviewSubmissions/SUB1"), [(m, p) for m, p, _ in client.requests])
        fresh = ProductClient({})
        quiet(asc_release.submit_for_review, fresh, APP, "AV1", "PREPARE_FOR_SUBMISSION", submission_id="SUB1")
        self.assertEqual([p for p, _ in fresh.posts], ["/reviewSubmissionItems"])

    def test_catalog_products_are_intended(self) -> None:
        self.assertEqual(asc_release.intended_product_ids(), {UNLOCK})


class CatalogTests(unittest.TestCase):
    def inputs(self) -> tuple[dict, dict, str]:
        return (
            json.loads((ROOT / "store" / "catalog" / "products.json").read_text()),
            json.loads((ROOT / "Abysm.storekit").read_text()),
            (ROOT / "Abysm" / "StoreManager.swift").read_text(),
        )

    def test_repo_catalog_matches_the_app(self) -> None:
        self.assertEqual(validate_catalog.validate(*self.inputs()), [UNLOCK])

    def test_mismatches_are_rejected(self) -> None:
        catalog, storekit, swift = self.inputs()
        broken = {
            "storekit": (catalog, {**storekit, "products": []}, swift),
            "entitlement": ({**catalog, "nonConsumables": [{"id": UNLOCK, "entitlement": "other"}]}, storekit, swift),
            "duplicate": ({**catalog, "consumables": [{"id": UNLOCK}]}, storekit, swift),
            "foreign id": ({**catalog, "nonConsumables": [{"id": "com.other.unlock"}]}, storekit, swift),
            "type": ({**catalog, "nonConsumables": [], "consumables": [{"id": UNLOCK}]}, storekit, swift),
            "product": (catalog, storekit, swift.replace(UNLOCK, "com.apoorvdarshan.Abysm.other")),
        }
        for label, args in broken.items():
            with self.subTest(label), self.assertRaises(validate_catalog.CatalogError):
                validate_catalog.validate(*args)


class AscCliTests(unittest.TestCase):
    def run_cli(self, env: dict[str, str], *args: str, dry_run: bool = True) -> tuple[int, str]:
        out = io.StringIO()
        full_env = {k: v for k, v in os.environ.items() if k not in ASC_FLAGS}
        full_env.update(env)
        argv = ["asc_release.py", *(["--dry-run"] if dry_run else []), *args]
        with mock.patch.dict(os.environ, full_env, clear=True), mock.patch.object(sys, "argv", argv), \
                redirect_stdout(out), redirect_stderr(out):
            try:
                asc_release.main()
            except SystemExit as exc:
                return (exc.code if isinstance(exc.code, int) else 1), out.getvalue()
        return 0, out.getvalue()

    def test_everything_off_is_a_no_op(self) -> None:
        code, output = self.run_cli({}, dry_run=False)
        self.assertEqual(code, 0)
        self.assertIn("skipped", output)

    def test_submit_without_this_runs_build_fails(self) -> None:
        code, output = self.run_cli({"SUBMIT_IOS_REVIEW": "true"})
        self.assertEqual(code, 1)
        self.assertIn("--build-id", output)

    def test_public_release_without_submit_fails(self) -> None:
        code, _ = self.run_cli({"UPLOAD_LISTING": "true", "PUBLIC_RELEASE": "true"})
        self.assertEqual(code, 1)

    def valid_tree(self) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return str(metadata_tree(tmp.name, {"description.txt": "D", "keywords.txt": "k"}))

    def test_whats_new_without_text_fails(self) -> None:
        # Turning What's New on needs whats_new.txt in every locale first.
        code, output = self.run_cli({"UPLOAD_WHATS_NEW": "true"}, "--metadata-dir", self.valid_tree())
        self.assertEqual(code, 1)
        self.assertIn("whats_new.txt", output)

    @repo_content
    def test_full_dry_run_with_repo_inputs(self) -> None:
        code, output = self.run_cli(
            {"UPLOAD_LISTING": "true", "UPLOAD_SCREENSHOTS": "true", "SUBMIT_IOS_REVIEW": "true"},
            "--build-id", "DRY-RUN", "--build-number", "3")
        self.assertEqual(code, 0, output)
        self.assertIn("no API calls", output)
        self.assertIn("screenshots=10", output)

    def test_live_run_requires_version_and_credentials(self) -> None:
        tree = self.valid_tree()
        for mode in ((), ("--preflight",)):
            with self.subTest(mode=mode):
                code, output = self.run_cli({"UPLOAD_LISTING": "true"}, "--metadata-dir", tree, *mode, dry_run=False)
                self.assertEqual(code, 1)
                self.assertIn("--version", output)
                code, output = self.run_cli(
                    {"UPLOAD_LISTING": "true", "APP_STORE_CONNECT_API_KEY_ID": "", "APP_STORE_CONNECT_ISSUER_ID": "",
                     "APP_STORE_CONNECT_API_KEY_P8": ""}, "--metadata-dir", tree, "--version", VERSION, *mode,
                    dry_run=False)
                self.assertEqual(code, 1)
                self.assertIn("missing ASC credentials", output)


IPHONE = "APP_IPHONE_67"
IPAD = "APP_IPAD_PRO_3GEN_129"
REPO_TEXT = {"description.txt": "D", "keywords.txt": "k", "whats_new.txt": "Fixes", "subtitle.txt": "Sub"}
LIVE_TEXT = {"description": "D", "keywords": "k", "whatsNew": "Fixes"}
LIVE_INFO = {"subtitle": "Sub"}


class FakeAsc:
    """App Store Connect stand-in for asc_release.main() (live path, no network).

    One app with one App Store version V1 (and its App Info), localizations for
    `locales`, screenshot sets, the build B9 this run uploaded, a draft review
    submission and the "Unlock the Deep" in-app purchase with its versions.
    """

    def __init__(self, *, state: str = "PREPARE_FOR_SUBMISSION", attached: str | None = "OLD",
                 revert_on_read: int | None = None, version_exists: bool = True, release_type: str | None = None,
                 version_text: dict | None = None, info_text: dict | None = None,
                 screenshots: dict[str, list[str]] | None = None,
                 screenshot_states: dict[str, list[str]] | None = None, unlock_state: str = "APPROVED",
                 unlock_versions: list[dict] | None = None, items: list[dict] | None = None,
                 locales: tuple[str, ...] = ("en-US",)) -> None:
        self.state = state
        self.attached = attached
        # The selection reads back as OLD from this read of /appStoreVersions/V1/build on.
        self.revert_on_read = revert_on_read
        self.version_exists = version_exists
        self.release_type = release_type
        self.version_text = dict(LIVE_TEXT if version_text is None else version_text)
        self.info_text = dict(LIVE_INFO if info_text is None else info_text)
        self.screenshots = screenshots or {}
        # assetDeliveryState of each screenshot in a set (COMPLETE unless given).
        self.screenshot_states = screenshot_states or {}
        self.unlock_state = unlock_state
        self.unlock_versions = unlock_versions if unlock_versions is not None else [
            {"id": "IV1", "attributes": {"version": 1, "state": "PREPARE_FOR_SUBMISSION"}}]
        self.items = list(items or [])
        self.locales = locales
        self.build_reads = 0
        self.calls: list[tuple[str, str]] = []
        self.bodies: list[tuple[str, str, dict | None]] = []

    def info_state(self) -> str:
        return "PREPARE_FOR_SUBMISSION" if self.state in asc_release.EDITABLE_VERSION_STATES else self.state

    def get(self, path: str) -> dict:
        self.calls.append(("GET", path))
        if path.startswith("/apps?"):
            return {"data": [{"id": APP, "attributes": {"bundleId": asc_release.DEFAULT_BUNDLE_ID}}]}
        if path.startswith(f"/apps/{APP}/appStoreVersions"):
            if not self.version_exists:
                return {"data": []}
            return {"data": [{"id": "V1", "attributes": {"versionString": VERSION, "appStoreState": self.state,
                                                         "releaseType": self.release_type}}]}
        if path.startswith("/appStoreVersions/V1/appStoreVersionLocalizations"):
            return {"data": [{"id": f"LOC-{loc}", "attributes": {"locale": loc, **self.version_text}}
                             for loc in self.locales]}
        if path.startswith(f"/apps/{APP}/appInfos"):
            return {"data": [{"id": "LIVE", "attributes": {"appStoreState": "READY_FOR_SALE"}},
                             {"id": "INFO", "attributes": {"appStoreState": self.info_state()}}]}
        if path.startswith("/appInfos/"):
            return {"data": [{"id": f"ILOC-{loc}", "attributes": {"locale": loc, **self.info_text}}
                             for loc in self.locales]}
        if path.startswith("/appStoreVersionLocalizations/") and "/appScreenshotSets" in path:
            return {"data": [{"id": f"SET-{kind}", "attributes": {"screenshotDisplayType": kind}}
                             for kind in self.screenshots]}
        if path.startswith("/appScreenshotSets/SET-"):
            kind = path.split("/")[2][len("SET-"):]
            checksums = self.screenshots[kind]
            states = self.screenshot_states.get(kind, ["COMPLETE"] * len(checksums))
            return {"data": [{"id": f"{kind}-{i}", "attributes": {"sourceFileChecksum": checksum,
                                                                 "assetDeliveryState": {"state": state}}}
                             for i, (checksum, state) in enumerate(zip(checksums, states))]}
        if path.startswith("/builds/B9"):
            return {"data": build_row("B9"), "included": [pre_row()]}
        if path == "/appStoreVersions/V1/build":
            self.build_reads += 1
            if self.revert_on_read is not None and self.build_reads >= self.revert_on_read:
                return {"data": {"type": "builds", "id": "OLD"}}
            return {"data": {"type": "builds", "id": self.attached} if self.attached else None}
        if path.startswith(f"/apps/{APP}/reviewSubmissions"):
            return {"data": [{"id": "SUB1"}]}
        if path.startswith("/reviewSubmissions/SUB1/items"):
            return {"data": self.items}
        if path.startswith(f"/apps/{APP}/subscriptionGroups"):
            return {"data": []}
        if path.startswith(f"/apps/{APP}/inAppPurchasesV2"):
            return {"data": [{"id": "IAP1", "attributes": {"name": "Unlock the Deep", "productId": UNLOCK,
                                                           "state": self.unlock_state}}]}
        if path == asc_release.iap_versions_path("IAP1"):
            return {"data": self.unlock_versions}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, body: dict) -> dict:
        self.calls.append(("POST", path))
        self.bodies.append(("POST", path, body))
        if path == "/reviewSubmissionItems":
            related = {k: v for k, v in body["data"]["relationships"].items() if k != "reviewSubmission"}
            self.items.append({"id": f"ITEM{len(self.items)}", "relationships": related})
        return {"data": {"id": "ITEM"}}

    def patch(self, path: str, body: dict) -> dict:
        self.calls.append(("PATCH", path))
        self.bodies.append(("PATCH", path, body))
        return {"data": body["data"]}

    def request(self, method: str, path: str, body: dict | None = None):
        self.calls.append((method, path))
        self.bodies.append((method, path, body))
        if method == "PATCH" and path == "/appStoreVersions/V1/relationships/build":
            self.attached = body["data"]["id"]
        return None

    def upload_bytes(self, url: str, data: bytes, headers: dict, *, method: str = "PUT") -> None:
        self.calls.append(("UPLOAD", url))

    def writes(self) -> list[tuple[str, str]]:
        return [call for call in self.calls if call[0] != "GET"]


SUBMIT = ("PATCH", "/reviewSubmissions/SUB1")
SELECT = ("PATCH", "/appStoreVersions/V1/relationships/build")


class MainFlow(unittest.TestCase):
    """Runs asc_release.main() against FakeAsc with a temporary listing and screenshots."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.metadata = metadata_tree(tmp.name, REPO_TEXT)
        iphone = Path(tmp.name) / "iphone"
        ipad = Path(tmp.name) / "ipad"
        iphone.mkdir()
        ipad.mkdir()
        self.shots = {
            IPHONE: [png(iphone / f"0{i}.png", 2796, 1290) for i in range(2)],
            IPAD: [png(ipad / f"0{i}.png", 2752, 2064) for i in range(2)],
        }
        # Distinct contents, so the checksums differ per file.
        for kind, files in self.shots.items():
            for i, path in enumerate(files):
                path.write_bytes(path.read_bytes() + f"{kind}{i}".encode())
        self.sets = (
            (IPHONE, iphone, frozenset({(2796, 1290)})),
            (IPAD, ipad, frozenset({(2752, 2064)})),
        )

    def repo_checksums(self) -> dict[str, list[str]]:
        return {kind: [asc_release.md5_hex(p) for p in files] for kind, files in self.shots.items()}

    def run_main(self, fake: FakeAsc, switches: dict[str, str], *args: str, build: bool = True) -> tuple[int, str]:
        argv = ["asc_release.py", "--version", VERSION, "--metadata-dir", str(self.metadata), *args]
        if build:
            argv += ["--build-id", "B9", "--build-number", "3"]
        env = {k: v for k, v in os.environ.items() if k not in ASC_FLAGS}
        env.update(switches)
        out = io.StringIO()
        code = 0
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(asc_release, "client_from_environment", return_value=fake), \
                mock.patch.object(asc_release, "SCREENSHOT_SETS", self.sets), \
                redirect_stdout(out), redirect_stderr(out):
            try:
                asc_release.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue()


SUBMIT_ONLY = {"SUBMIT_IOS_REVIEW": "true"}
TEXT_AND_SUBMIT = {"UPLOAD_LISTING": "true", "UPLOAD_WHATS_NEW": "true", "SUBMIT_IOS_REVIEW": "true"}
EVERYTHING = {**TEXT_AND_SUBMIT, "UPLOAD_SCREENSHOTS": "true"}


class LiveSubmitFlowTests(MainFlow):
    def test_selects_rechecks_then_submits(self) -> None:
        fake = FakeAsc()
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 0, output)
        calls = fake.calls
        select = calls.index(SELECT)
        submit = calls.index(SUBMIT)
        reads = [i for i, c in enumerate(calls) if c == ("GET", "/appStoreVersions/V1/build")]
        build_checks = [i for i, c in enumerate(calls) if c[0] == "GET" and c[1].startswith("/builds/B9")]
        self.assertEqual(len(reads), 3, "checked before selecting, read back, and rechecked")
        self.assertTrue(reads[0] < select < reads[1] < reads[2] < submit)
        self.assertEqual(len(build_checks), 2)
        self.assertTrue(build_checks[1] < reads[2] < submit, "build must be re-verified just before submit")
        self.assertIn(("PATCH", "/appStoreVersions/V1"), calls)  # release type
        self.assertEqual(item_targets([(p, b) for m, p, b in fake.bodies if m == "POST"]), [("appStoreVersion", "V1")])

    def test_unlock_goes_out_with_the_version_never_on_its_own(self) -> None:
        fake = FakeAsc(unlock_state="READY_TO_SUBMIT")
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 0, output)
        posts = [(p, b) for m, p, b in fake.bodies if m == "POST"]
        self.assertEqual(item_targets(posts), [("inAppPurchaseVersion", "IV1"), ("appStoreVersion", "V1")])
        self.assertNotIn(("POST", "/inAppPurchaseSubmissions"), fake.calls)
        self.assertEqual(fake.calls.count(SUBMIT), 1, "one submit sends the version and its products")

    def test_selection_changed_before_submit_aborts_without_any_review_write(self) -> None:
        # Pre-check (1) and read-back (2) see this run's build; the final recheck (3) does not.
        fake = FakeAsc(revert_on_read=3, unlock_state="READY_TO_SUBMIT")
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 1)
        self.assertIn("not submitting", output)
        self.assertNotIn(SUBMIT, fake.calls)
        self.assertNotIn(("POST", "/inAppPurchaseSubmissions"), fake.calls)
        # Unlock the Deep only joined the unsubmitted draft; nothing reached App Review.
        self.assertEqual(item_targets([(p, b) for m, p, b in fake.bodies if m == "POST"]),
                         [("inAppPurchaseVersion", "IV1")])

    def test_waiting_for_review_with_another_build_aborts(self) -> None:
        fake = FakeAsc(state="WAITING_FOR_REVIEW", attached="OTHER")
        code, _ = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 1)
        self.assertEqual(fake.writes(), [])

    def test_waiting_for_review_with_this_build_is_idempotent(self) -> None:
        fake = FakeAsc(state="WAITING_FOR_REVIEW", attached="B9")
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.writes(), [])
        self.assertIn("already WAITING_FOR_REVIEW", output)

    def test_live_version_is_not_submitted(self) -> None:
        fake = FakeAsc(state="READY_FOR_SALE")
        code, _ = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 1)
        self.assertEqual(fake.writes(), [])


class RerunTests(MainFlow):
    """Re-running the store step after a partly finished submission (IOS-REL-3)."""

    def test_ready_for_review_rerun_with_text_switches_submits(self) -> None:
        # The first attempt left the version in the draft with this run's build; its
        # submit PATCH failed. Text still matches the repo, so only the submit is sent.
        fake = FakeAsc(state="READY_FOR_REVIEW", attached="B9", release_type="MANUAL",
                       items=[{"id": "I1", "relationships": {"appStoreVersion": {"data": {"id": "V1"}}}}])
        code, output = self.run_main(fake, TEXT_AND_SUBMIT)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.writes(), [SUBMIT])

    def test_ready_for_review_text_can_still_change(self) -> None:
        fake = FakeAsc(state="READY_FOR_REVIEW", attached="B9", release_type="MANUAL", version_text={**LIVE_TEXT, "whatsNew": "Old"})
        code, output = self.run_main(fake, TEXT_AND_SUBMIT)
        self.assertEqual(code, 0, output)
        self.assertIn(("PATCH", "/appStoreVersionLocalizations/LOC-en-US"), fake.calls)
        self.assertEqual(fake.calls[-1], SUBMIT)

    def test_ready_for_review_screenshots_must_already_match(self) -> None:
        same = FakeAsc(state="READY_FOR_REVIEW", attached="B9", release_type="MANUAL", screenshots=self.repo_checksums())
        code, output = self.run_main(same, EVERYTHING)
        self.assertEqual(code, 0, output)
        self.assertEqual(same.writes(), [SUBMIT])  # the version is already in the draft
        changed = self.repo_checksums()
        changed[IPAD] = list(reversed(changed[IPAD]))
        differs = FakeAsc(state="READY_FOR_REVIEW", attached="B9", release_type="MANUAL", screenshots=changed)
        code, output = self.run_main(differs, EVERYTHING)
        self.assertEqual(code, 1)
        self.assertIn("screenshots cannot change while the version is READY_FOR_REVIEW", output)
        self.assertEqual(differs.writes(), [])
        # The repo's checksums are not enough: Apple must have processed every image.
        unprocessed = FakeAsc(state="READY_FOR_REVIEW", attached="B9", release_type="MANUAL",
                              screenshots=self.repo_checksums(),
                              screenshot_states={IPHONE: ["UPLOAD_COMPLETE", "COMPLETE"]})
        code, output = self.run_main(unprocessed, EVERYTHING)
        self.assertEqual(code, 1, output)
        self.assertIn("UPLOAD_COMPLETE", output)
        self.assertEqual(unprocessed.writes(), [])

    def test_submitted_rerun_passes_only_when_nothing_would_change(self) -> None:
        for state in sorted(asc_release.SUBMITTED_VERSION_STATES):
            with self.subTest(state=state):
                same = FakeAsc(state=state, attached="B9", screenshots=self.repo_checksums())
                code, output = self.run_main(same, EVERYTHING)
                self.assertEqual(code, 0, output)
                self.assertEqual(same.writes(), [])
                for fake in (FakeAsc(state=state, attached="B9", screenshots=self.repo_checksums(),
                                     version_text={**LIVE_TEXT, "whatsNew": "Old"}),
                             FakeAsc(state=state, attached="B9", screenshots=self.repo_checksums(),
                                     info_text={"subtitle": "Old"}),
                             FakeAsc(state=state, attached="B9", screenshots={}),
                             FakeAsc(state=state, attached="B9", screenshots=self.repo_checksums(),
                                     screenshot_states={IPAD: ["COMPLETE", "FAILED"]}),
                             FakeAsc(state=state, attached="B9", screenshots=self.repo_checksums(),
                                     unlock_state="READY_TO_SUBMIT"),
                             FakeAsc(state=state, attached="OTHER", screenshots=self.repo_checksums())):
                    code, output = self.run_main(fake, EVERYTHING)
                    self.assertEqual(code, 1, output)
                    self.assertEqual(fake.writes(), [])

    def test_submitted_rerun_never_sends_a_product_to_review_on_its_own(self) -> None:
        # Unlock the Deep is Ready to Submit while the version is already in review, so
        # it did not go out with the version. The re-run names it and writes nothing:
        # no draft, no review item and no product-only submission.
        for state in sorted(asc_release.SUBMITTED_VERSION_STATES):
            with self.subTest(state=state):
                fake = FakeAsc(state=state, attached="B9", unlock_state="READY_TO_SUBMIT")
                code, output = self.run_main(fake, SUBMIT_ONLY)
                self.assertEqual(code, 1, output)
                self.assertEqual(fake.writes(), [])
                self.assertIn(f"in-app purchase Unlock the Deep ({UNLOCK})", output)
                self.assertIn("never sent to App Review without the version", output)

    def test_an_identical_rerun_in_an_editable_state_sends_nothing_but_the_submit(self) -> None:
        fake = FakeAsc(attached="B9", release_type="MANUAL", screenshots=self.repo_checksums())
        code, output = self.run_main(fake, EVERYTHING)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.writes(), [("POST", "/reviewSubmissionItems"), SUBMIT])


class PreflightTests(MainFlow):
    """`asc_release.py --preflight`: read-only, before anything is built (IOS-REL-2)."""

    def preflight(self, fake: FakeAsc, switches: dict[str, str]) -> tuple[int, str]:
        code, output = self.run_main(fake, switches, "--preflight", build=False)
        self.assertEqual(fake.writes(), [], "the preflight must never change App Store Connect")
        return code, output

    def test_missing_version_fails_with_the_fix(self) -> None:
        code, output = self.preflight(FakeAsc(version_exists=False), {"UPLOAD_LISTING": "true"})
        self.assertEqual(code, 1)
        self.assertIn("create the version in App Store Connect first", output)

    def test_ready_version_passes_and_reports_what_would_change(self) -> None:
        fake = FakeAsc(version_text={**LIVE_TEXT, "description": "Old"}, unlock_state="READY_TO_SUBMIT")
        code, output = self.preflight(fake, EVERYTHING)
        self.assertEqual(code, 0, output)
        self.assertIn("would update description", output)
        self.assertIn("would replace", output)
        self.assertIn("Unlock the Deep", output)
        self.assertIn("preflight passed", output)

    def test_a_submitted_version_cannot_take_a_new_build(self) -> None:
        for state in sorted(asc_release.SUBMITTED_VERSION_STATES):
            with self.subTest(state=state):
                code, output = self.preflight(FakeAsc(state=state, attached="B8"), SUBMIT_ONLY)
                self.assertEqual(code, 1)
                self.assertIn(f"already {state}", output)

    def test_submitted_version_with_text_switches_only_compares(self) -> None:
        code, output = self.preflight(FakeAsc(state="WAITING_FOR_REVIEW"), {"UPLOAD_LISTING": "true"})
        self.assertEqual(code, 0, output)
        code, _ = self.preflight(FakeAsc(state="WAITING_FOR_REVIEW", info_text={"subtitle": "Old"}),
                                 {"UPLOAD_LISTING": "true"})
        self.assertEqual(code, 1)

    def test_screenshots_apple_has_not_processed_are_never_taken_as_done(self) -> None:
        states = {IPAD: ["COMPLETE", "FAILED"]}
        code, output = self.preflight(FakeAsc(screenshots=self.repo_checksums(), screenshot_states=states),
                                      {"UPLOAD_SCREENSHOTS": "true"})
        self.assertEqual(code, 0, output)
        self.assertIn(f"{IPHONE} (en-US): 2 screenshot(s) already match the repo", output)
        self.assertIn(f"{IPAD} (en-US): screenshots match the repo but are not all processed", output)
        self.assertIn("would replace", output)
        # Once screenshots are locked, a failed image fails the preflight before the build.
        locked = FakeAsc(state="READY_FOR_REVIEW", screenshots=self.repo_checksums(), screenshot_states=states)
        code, output = self.preflight(locked, {"UPLOAD_SCREENSHOTS": "true"})
        self.assertEqual(code, 1, output)
        self.assertIn(f"{IPAD}-1: FAILED", output)

    def test_states_and_inputs_that_would_stop_the_store_step_fail_early(self) -> None:
        cases = {
            "live version": (FakeAsc(state="READY_FOR_SALE"), {"UPLOAD_LISTING": "true"}, "not editable"),
            "approved version, submit": (FakeAsc(state="PENDING_DEVELOPER_RELEASE"), SUBMIT_ONLY, "cannot be submitted"),
            "unlock without a version": (FakeAsc(unlock_state="READY_TO_SUBMIT", unlock_versions=[]), SUBMIT_ONLY,
                                         "cannot be added to App Review"),
            "locale missing in App Store Connect": (FakeAsc(locales=("de-DE",)), {"UPLOAD_WHATS_NEW": "true"},
                                                    "no en-US localization"),
            "App Info locked": (FakeAsc(state="READY_FOR_REVIEW", info_text={"subtitle": "Old"}),
                                {"UPLOAD_LISTING": "true"}, "no App Info is editable"),
        }
        for label, (fake, switches, message) in cases.items():
            if label == "App Info locked":
                fake.info_state = lambda: "WAITING_FOR_REVIEW"  # type: ignore[method-assign]
            with self.subTest(label):
                code, output = self.preflight(fake, switches)
                self.assertEqual(code, 1, output)
                self.assertIn(message, output)

    def test_preflight_needs_no_build_and_dry_run_is_separate(self) -> None:
        code, output = self.preflight(FakeAsc(), SUBMIT_ONLY)
        self.assertEqual(code, 0, output)
        code, output = self.run_main(FakeAsc(), {"UPLOAD_LISTING": "true"}, "--preflight", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("separate modes", output)

    def test_read_only_client_refuses_every_write(self) -> None:
        fake = FakeAsc()
        client = asc_release.ReadOnlyClient(fake)
        self.assertEqual(client.get("/apps?x")["data"][0]["id"], APP)
        for write in (lambda: client.post("/reviewSubmissions", {}),
                      lambda: client.patch("/appStoreVersions/V1", {}),
                      lambda: client.request("PATCH", "/reviewSubmissions/SUB1", body={}),
                      lambda: client.request("DELETE", "/appScreenshots/S1"),
                      lambda: client.upload_bytes("https://upload.example", b"", {})):
            with self.assertRaises(asc_release.ReadOnlyViolation):
                write()
        self.assertEqual(fake.writes(), [])


class ReleaseNotesTests(unittest.TestCase):
    TEXT = "# Notes\n\n## Unreleased\n\n- next\n\n## v1.0.1\n\n- Fixes\n\n## v1.0.2\n\n"

    def test_exact_tag_section(self) -> None:
        self.assertEqual(release_notes.section(self.TEXT, "v1.0.1"), "- Fixes")
        self.assertIsNone(release_notes.section(self.TEXT, "v1.0"))
        self.assertIsNone(release_notes.section(self.TEXT, "Unreleased"))
        self.assertEqual(release_notes.section(self.TEXT, "v1.0.2"), "")

    def test_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp) / "RELEASE_NOTES.md"
            notes.write_text(self.TEXT)
            with mock.patch.object(release_notes, "NOTES", notes):
                out = io.StringIO()
                with redirect_stdout(out), redirect_stderr(io.StringIO()):
                    self.assertEqual(release_notes.main(["v1.0.1"]), 0)
                    self.assertEqual(release_notes.main(["v9.9"]), release_notes.MISSING)
                    self.assertEqual(release_notes.main(["v1.0.2"]), 1)
                self.assertEqual(out.getvalue().strip(), "- Fixes")

    def test_missing_notes_file_means_generated_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(release_notes, "NOTES", Path(tmp) / "RELEASE_NOTES.md"):
                self.assertEqual(quiet(release_notes.main, ["v1.0.1"]), release_notes.MISSING)

    def test_duplicate_sections_for_the_tag_are_rejected(self) -> None:
        text = self.TEXT + "## v1.0.1\n\n- A second, different section\n"
        with self.assertRaisesRegex(ValueError, "2 '## v1.0.1' sections"):
            release_notes.section(text, "v1.0.1")
        self.assertEqual(release_notes.section(text, "v1.0.2"), "")  # other tags are unaffected
        self.assertEqual(release_notes.duplicate_headings(text), ["v1.0.1"])
        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp) / "RELEASE_NOTES.md"
            notes.write_text(text)
            err = io.StringIO()
            with mock.patch.object(release_notes, "NOTES", notes), redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(release_notes.main(["v1.0.1"]), 1)
            self.assertIn("keep exactly one", err.getvalue())

    @repo_content
    def test_repository_release_notes_have_one_section_per_heading(self) -> None:
        text = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        self.assertEqual(release_notes.duplicate_headings(text), [])


class PrintGatesTests(unittest.TestCase):
    def output(self, env: dict[str, str]) -> str:
        names = print_gates.GATES + tuple(name for name, *_ in print_gates.TIMING)
        clean = {k: v for k, v in os.environ.items() if k not in names}
        out = io.StringIO()
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True), redirect_stdout(out):
            print_gates.main()
        return out.getvalue()

    def test_invalid_values_are_shown_as_invalid_not_off(self) -> None:
        output = self.output({"IOS_RELEASE_AUTOMATION": "true", "IOS_UPLOAD_BUILD": "maybe",
                              "IOS_BUILD_POLL_SECONDS": "5", "IOS_BUILD_WAIT_MINUTES": "ninety"})
        self.assertIn("IOS_UPLOAD_BUILD=INVALID 'maybe' (a release run fails)", output)
        self.assertIn("IOS_BUILD_POLL_SECONDS=INVALID '5'", output)
        self.assertIn("IOS_BUILD_WAIT_MINUTES=INVALID 'ninety'", output)
        self.assertIn("ERROR: IOS_UPLOAD_BUILD, IOS_BUILD_POLL_SECONDS, IOS_BUILD_WAIT_MINUTES invalid", output)

    def test_valid_unset_and_default_values(self) -> None:
        output = self.output({"IOS_RELEASE_AUTOMATION": " Yes ", "IOS_UPLOAD_LISTING": "off",
                              "IOS_BUILD_WAIT_MINUTES": "300"})
        self.assertIn("IOS_RELEASE_AUTOMATION=true", output)
        self.assertIn("IOS_UPLOAD_LISTING=false\n", output)
        self.assertIn("IOS_SUBMIT_REVIEW=false (unset)", output)
        self.assertIn("IOS_BUILD_POLL_SECONDS=30 (default)", output)
        self.assertIn("IOS_BUILD_WAIT_MINUTES=300", output)
        self.assertNotIn("INVALID", output)
        self.assertIn("no store operation is enabled", output)
        self.assertIn("IOS_RELEASE_AUTOMATION is off", self.output({}))

    def test_same_rules_as_the_gates(self) -> None:
        self.assertEqual(print_gates.GATES, (ios_release.MASTER,) + tuple(n for n, _ in ios_release.OPERATION_SWITCHES))
        self.assertEqual(print_gates.TIMING, (ios_release.POLL_SECONDS, ios_release.WAIT_MINUTES))
        self.assertEqual((print_gates.TRUE_VALUES, print_gates.FALSE_VALUES),
                         (ios_release.TRUE_VALUES, ios_release.FALSE_VALUES))


class RedactLogsTests(unittest.TestCase):
    SECRETS = {"ASC_KEY_ID": "AB1C2D3E4F", "ASC_ISSUER_ID": "69a6de7f-0000-4000-8000-123456789abc"}

    def tree(self, tmp: str) -> Path:
        root = Path(tmp) / "logs"
        (root / "dist.xcdistributionlogs").mkdir(parents=True)
        key, issuer = self.SECRETS["ASC_KEY_ID"], self.SECRETS["ASC_ISSUER_ID"]
        (root / "archive.log").write_text(f"-authenticationKeyID {key} -authenticationKeyIssuerID {issuer}\nAB1XC2\n")
        (root / "dist.xcdistributionlogs" / "binary.plist").write_bytes(b"bplist00\x00\x01" + key.encode() + b"\x00")
        (root / "dist.xcdistributionlogs" / "le.txt").write_bytes(f"key={key}".encode("utf-16-le"))
        (root / "dist.xcdistributionlogs" / "be.txt").write_bytes(("\ufeff" + f"issuer={issuer}").encode("utf-16-be"))
        return root

    def run_cli(self, root: Path, env: dict[str, str] | None = None) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.dict(os.environ, env if env is not None else self.SECRETS), \
                redirect_stdout(out), redirect_stderr(out):
            code = redact_logs.main([str(root), "ASC_KEY_ID", "ASC_ISSUER_ID"])
        return code, out.getvalue()

    def everything(self, root: Path) -> bytes:
        return b"".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())

    def test_every_file_and_encoding_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(tmp)
            code, output = self.run_cli(root)
            self.assertEqual(code, 0, output)
            self.assertEqual(
                (root / "archive.log").read_text(),
                "-authenticationKeyID <ASC_KEY_ID> -authenticationKeyIssuerID <ASC_ISSUER_ID>\nAB1XC2\n",
            )
            self.assertIn(b"<ASC_KEY_ID>", (root / "dist.xcdistributionlogs" / "binary.plist").read_bytes())
            self.assertEqual((root / "dist.xcdistributionlogs" / "le.txt").read_bytes().decode("utf-16-le"),
                             "key=<ASC_KEY_ID>")
            self.assertEqual((root / "dist.xcdistributionlogs" / "be.txt").read_bytes().decode("utf-16-be"),
                             "\ufeffissuer=<ASC_ISSUER_ID>")
            self.assertFalse(redact_logs.leaks(self.everything(root), self.SECRETS))

    def test_links_and_unredactable_files_are_removed_never_followed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(tmp)
            outside = Path(tmp) / "AuthKey.p8"
            outside.write_text(f"secret key for {self.SECRETS['ASC_KEY_ID']}")
            (root / "key-link").symlink_to(outside)
            (root / "dir-link").symlink_to(Path(tmp), target_is_directory=True)
            locked = root / "locked.log"
            locked.write_text(self.SECRETS["ASC_KEY_ID"])
            with mock.patch.object(redact_logs.Path, "write_bytes", side_effect=PermissionError("read-only")):
                code, output = self.run_cli(root)
            self.assertEqual(code, 0, output)
            self.assertFalse((root / "key-link").is_symlink())
            self.assertFalse((root / "dir-link").is_symlink())
            self.assertFalse(locked.exists())  # could not be rewritten, so it was removed
            self.assertIn(self.SECRETS["ASC_KEY_ID"], outside.read_text())  # a link target is never touched
            self.assertFalse(redact_logs.leaks(self.everything(root), self.SECRETS))

    def test_fails_when_a_dirty_file_cannot_be_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(tmp)
            with mock.patch.object(redact_logs.Path, "write_bytes", side_effect=PermissionError("read-only")), \
                    mock.patch.object(redact_logs, "remove", return_value=False):
                code, output = self.run_cli(root)
            self.assertEqual(code, 1)
            self.assertIn("must not be uploaded", output)

    def test_unset_ids_and_missing_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(tmp)
            before = self.everything(root)
            code, _ = self.run_cli(root, env={"ASC_KEY_ID": "", "ASC_ISSUER_ID": ""})
            self.assertEqual((code, self.everything(root)), (0, before))
            self.assertEqual(self.run_cli(Path(tmp) / "absent")[0], 0)


class ExportListingTests(unittest.TestCase):
    def test_writes_fields_and_removes_cleared_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            loc = Path(tmp)
            (loc / "whats_new.txt").write_text("old")
            written = export_listing.write_fields(
                loc, {"description": "Desc\n", "keywords": "", "whatsNew": None},
                asc_release.LISTING_FIELDS + (asc_release.WHATS_NEW_FIELD,))
            self.assertEqual(written, ["description.txt"])
            self.assertEqual((loc / "description.txt").read_text(), "Desc\n")
            self.assertFalse((loc / "whats_new.txt").exists())

    def test_picks_the_live_version_unless_asked(self) -> None:
        versions = [
            {"id": "A", "attributes": {"versionString": "1.0", "appStoreState": "READY_FOR_SALE"}},
            {"id": "B", "attributes": {"versionString": "1.0.1", "appStoreState": "PREPARE_FOR_SUBMISSION"}},
        ]
        self.assertEqual(export_listing.pick_version(versions, None)["id"], "A")
        self.assertEqual(export_listing.pick_version(versions, "1.0.1")["id"], "B")
        with self.assertRaises(SystemExit):
            quiet(export_listing.pick_version, versions, "2.0")


# Stand-in for `xcrun simctl spawn SIM launchctl list`: a long job list written in
# many small writes, like launchctl, so a reader that quits early breaks the pipe.
FAKE_XCRUN = r"""#!/bin/bash
[ "$*" = "simctl spawn SIM launchctl list" ] || exit 64
printf 'PID\tStatus\tLabel\n'
for ((i = 0; i < 20000; i++)); do
  if (( i == LABEL_AT )); then printf '123\t0\tUIKitApplication:com.apoorvdarshan.Abysm[1a2b][rb-legacy]\n'; fi
  printf -- '-\t0\tcom.apple.job.%d\n' "$i"
done
exit STATUS
"""


class IosTestScriptTests(unittest.TestCase):
    """scripts/test-ios.sh: the check that the unit-test host app has exited (fake xcrun, no simulator)."""

    SCRIPT = (ROOT / "scripts" / "test-ios.sh").read_text()

    def app_running(self, *, label_at: int | None, status: int = 0) -> subprocess.CompletedProcess:
        """Run the script's app_running() under its own shell options against FAKE_XCRUN."""
        function = re.search(r"^app_running\(\) \{\n.*?^\}\n", self.SCRIPT, re.M | re.S)
        self.assertIsNotNone(function, "app_running() in scripts/test-ios.sh")
        with tempfile.TemporaryDirectory() as tmp:
            xcrun = Path(tmp) / "xcrun"
            xcrun.write_text(FAKE_XCRUN.replace("LABEL_AT", str(-1 if label_at is None else label_at))
                             .replace("STATUS", str(status)))
            xcrun.chmod(0o755)
            harness = "\n".join([
                re.search(r"^set -euo pipefail$", self.SCRIPT, re.M).group(0),
                "simulator_id=SIM",
                re.search(r'^app_bundle_id="com\.apoorvdarshan\.Abysm"$', self.SCRIPT, re.M).group(0),
                function.group(0),
                "if app_running; then echo RUNNING; else echo GONE; fi",
            ])
            return subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=120, check=False,
                                  env=dict(os.environ, PATH=f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}"))

    def test_a_running_app_is_seen_wherever_launchctl_lists_it(self) -> None:
        # Piped into `grep -q` under pipefail, an early match let grep quit, launchctl
        # died of SIGPIPE, and the still-running app read as gone.
        for label_at in (0, 5, 19999):
            with self.subTest(label_at=label_at):
                result = self.app_running(label_at=label_at)
                self.assertEqual((result.returncode, result.stdout.strip()), (0, "RUNNING"), result.stderr)

    def test_an_exited_app_is_seen_as_gone(self) -> None:
        result = self.app_running(label_at=None)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "GONE"), result.stderr)

    def test_an_unreadable_job_list_stops_the_run(self) -> None:
        # Unknown is not "gone": the UI tests must not start without knowing.
        result = self.app_running(label_at=None, status=3)
        self.assertEqual((result.returncode, result.stdout), (1, ""), result.stderr)
        self.assertIn("cannot list the simulator's launchd jobs", result.stderr)


class WorkflowWiringTests(unittest.TestCase):
    WORKFLOW = (ROOT / ".github" / "workflows" / "ios-release.yml").read_text()

    def test_every_switch_reaches_the_gates_step(self) -> None:
        for name, _ in ios_release.OPERATION_SWITCHES + ((ios_release.MASTER, None),):
            self.assertIn(f"{name}: ${{{{ vars.{name} }}}}", self.WORKFLOW, name)
        for name in (ios_release.POLL_SECONDS[0], ios_release.WAIT_MINUTES[0]):
            self.assertIn(f"{name}: ${{{{ vars.{name} }}}}", self.WORKFLOW, name)

    def test_only_tag_runs_upload_and_validation_never_does(self) -> None:
        self.assertIn("if: env.MODE == 'release'", self.WORKFLOW)
        self.assertIn('tags:\n      - "v*"', self.WORKFLOW)
        self.assertNotIn("pull_request", self.WORKFLOW)

    def job(self, name: str) -> str:
        """Text of one top-level job, up to the next job (jobs are indented two spaces)."""
        match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", self.WORKFLOW, re.M | re.S)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_tag_runs_queue_in_one_group(self) -> None:
        # Releases run one at a time, a third run never cancels a pending one,
        # and each validation run keeps its own group.
        self.assertIn(
            "group: ios-release-${{ github.event_name == 'push' && 'release' || github.run_id }}",
            self.WORKFLOW,
        )
        self.assertIn("cancel-in-progress: false", self.WORKFLOW)
        self.assertRegex(self.WORKFLOW, r"(?m)^  queue: max$")

    def test_build_wait_is_its_own_job(self) -> None:
        wait = self.job("wait-for-build")
        self.assertIn("needs: [quality, prepare, build]", wait)
        self.assertIn("needs.prepare.outputs.upload_build == 'true'", wait)
        self.assertIn("needs.build.result == 'success'", wait)
        self.assertIn("build_id: ${{ steps.wait.outputs.build_id }}", wait)
        self.assertIn("ios_release.py wait-build", wait)
        timeout = int(re.search(r"timeout-minutes: (\d+)", wait).group(1))
        self.assertGreater(timeout, ios_release.WAIT_MINUTES[3])
        self.assertEqual(self.WORKFLOW.count("ios_release.py wait-build"), 1)

        store = self.job("app-store-connect")
        self.assertIn("needs: [quality, prepare, build, wait-for-build]", store)
        self.assertIn("BUILD_ID: ${{ needs.wait-for-build.outputs.build_id }}", store)
        self.assertIn("needs.prepare.outputs.asc == 'true'", store)
        self.assertNotIn("steps.wait", store)

        release = self.job("github-release")
        self.assertIn("needs: [quality, prepare, build, wait-for-build, app-store-connect]", release)
        self.assertIn(
            "(needs.wait-for-build.result == 'success' || needs.wait-for-build.result == 'skipped')",
            release,
        )

    def step(self, job: str, name: str) -> str:
        """Text of one step of a job, from its `- name:` line to the next step."""
        body = self.job(job)
        start = body.index(f"      - name: {name}\n")
        end = body.find("\n      - ", start + 1)
        return body[start:] if end == -1 else body[start:end]

    def test_build_logs_are_redacted_before_upload(self) -> None:
        build = self.job("build")
        self.assertIn("name: ios-release-logs-${{ github.run_id }}-${{ github.run_attempt }}", build)
        self.assertIn("/scripts/store/redact_logs.py", build)  # in the sparse checkout
        collect = self.step("build", "Collect logs")
        self.assertIn("id: collect-logs", collect)
        self.assertIn('python3 scripts/store/redact_logs.py "$RUNNER_TEMP/logs" ASC_KEY_ID ASC_ISSUER_ID', collect)
        self.assertNotIn("|| true", collect.split("redact_logs.py", 1)[1])  # a failed redaction fails the step
        keep = self.step("build", "Keep build logs")
        # Nothing is uploaded unless redaction succeeded.
        self.assertIn("if: failure() && steps.collect-logs.outcome == 'success'", keep)
        self.assertLess(build.index("redact_logs.py \"$RUNNER_TEMP/logs\""), build.index("actions/upload-artifact"))
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "logs"
            logs.mkdir()
            (logs / "archive.log").write_text("-authenticationKeyID AB1.C2 -authenticationKeyIssuerID 69a6-de7f\nAB1XC2\n")
            (logs / "dist.bin").write_bytes(b"\x00\x01AB1.C2\x00" + "69a6-de7f".encode("utf-16-le"))
            env = dict(os.environ, ASC_KEY_ID="AB1.C2", ASC_ISSUER_ID="69a6-de7f")
            subprocess.run([sys.executable, str(HERE / "redact_logs.py"), str(logs), "ASC_KEY_ID", "ASC_ISSUER_ID"],
                           env=env, check=True, capture_output=True)
            self.assertEqual(
                (logs / "archive.log").read_text(),
                "-authenticationKeyID <ASC_KEY_ID> -authenticationKeyIssuerID <ASC_ISSUER_ID>\nAB1XC2\n",
            )
            self.assertEqual((logs / "dist.bin").read_bytes(),
                             b"\x00\x01<ASC_KEY_ID>\x00" + "<ASC_ISSUER_ID>".encode("utf-16-le"))

    def test_app_store_version_preflight_runs_before_the_build_on_tag_runs_only(self) -> None:
        prepare = self.job("prepare")
        preflight = self.step("prepare", "Check the App Store version (read-only preflight)")
        # asc is only ever on for a tag run (validation runs resolve every switch off).
        self.assertIn("if: steps.gates.outputs.asc == 'true'", preflight)
        self.assertIn('python3 -u scripts/store/asc_release.py --preflight --version "$MARKETING_VERSION"', preflight)
        self.assertIn("MARKETING_VERSION: ${{ steps.gates.outputs.marketing_version }}", preflight)
        for flag, output in (("UPLOAD_LISTING", "listing"), ("UPLOAD_WHATS_NEW", "whats_new"),
                             ("UPLOAD_SCREENSHOTS", "screenshots"), ("SUBMIT_IOS_REVIEW", "submit"),
                             ("PUBLIC_RELEASE", "public_release")):
            self.assertIn(f"{flag}: ${{{{ steps.gates.outputs.{output} }}}}", preflight)
        self.assertNotIn("--build-id", preflight)
        install = prepare.index("      - name: Install store tooling\n")
        self.assertIn("if: steps.gates.outputs.build == 'true' || steps.gates.outputs.asc == 'true'",
                      self.step("prepare", "Install store tooling"))
        self.assertLess(install, prepare.index("Check the App Store version (read-only preflight)"))
        self.assertLess(prepare.index("--preflight"), prepare.index("ios_release.py build-number"))
        self.assertIn("needs.prepare.result == 'success'", self.job("build"))  # the build waits for it
        self.assertEqual(gates({}, event="workflow_dispatch", ref="main")["asc"], False)

    def test_unused_store_assets_never_block_a_release(self) -> None:
        offline = self.step("prepare", "Check the release tooling and inputs (offline)")
        self.assertIn("STORE_TESTS_SCOPE: release", offline)
        # The listing/screenshot checks a release does run are the gated dry run's.
        self.assertIn("UPLOAD_LISTING: ${{ steps.gates.outputs.listing }}", offline)
        self.assertIn("UPLOAD_SCREENSHOTS: ${{ steps.gates.outputs.screenshots }}", offline)
        checks = (ROOT / ".github" / "workflows" / "store-checks.yml").read_text()
        self.assertNotIn("STORE_TESTS_SCOPE", checks)  # PRs and main check every asset
        env = {k: v for k, v in os.environ.items() if k != "STORE_TESTS_SCOPE"}
        tests = [f"test_ios_release.{name}" for name in REPO_CONTENT_TESTS + ("CatalogTests.test_repo_catalog_matches_the_app",)]
        for scope, skipped in (("release", len(REPO_CONTENT_TESTS)), ("", 0)):
            result = subprocess.run([sys.executable, "-m", "unittest", "-v", *tests], cwd=HERE, capture_output=True,
                                    text=True, env=dict(env, STORE_TESTS_SCOPE=scope), check=False)
            with self.subTest(scope=scope):
                self.assertEqual(result.stderr.count("skipped 'release run"), skipped, result.stderr)
                # The catalog check always runs: it covers the products the build sells.
                # (Pass or fail of the real-file checks is reported by the normal run.)
                self.assertRegex(result.stderr, r"test_repo_catalog_matches_the_app .*\.\.\. (ok|FAIL)")

    def test_store_tooling_uses_a_pinned_python_never_the_system_one(self) -> None:
        for workflow in ("ios-release.yml", "store-checks.yml"):
            text = (ROOT / ".github" / "workflows" / workflow).read_text()
            for match in re.finditer(r"^  ([A-Za-z0-9_-]+):\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", text.split("\njobs:\n", 1)[1],
                                     re.M | re.S):
                job, body = match.group(1), match.group(2)
                if "pip install" not in body:
                    continue
                with self.subTest(workflow=workflow, job=job):
                    setup = body.find("actions/setup-python@")
                    self.assertGreater(setup, -1)
                    self.assertLess(setup, body.index("pip install"))
                    self.assertRegex(body, r"actions/setup-python@[0-9a-f]{40} # v\d")
                    self.assertIn('python-version: "3.13"', body)

    def test_store_steps_run_unbuffered(self) -> None:
        for command in ("ios_release.py build-number", "ios_release.py wait-build", "asc_release.py --preflight",
                        'asc_release.py "${args[@]}"'):
            with self.subTest(command=command):
                self.assertIn(f"python3 -u scripts/store/{command}", self.WORKFLOW)
                self.assertNotIn(f"python3 scripts/store/{command}", self.WORKFLOW)

    def test_job_outputs_reach_the_build_wait_through_env(self) -> None:
        wait = self.step("wait-for-build", "Wait for App Store Connect to process this build")
        script = wait.split("run: |\n", 1)[1]
        self.assertNotIn("${{", script)
        for name, output in (("BUILD_NUMBER", "needs.prepare.outputs.build_number"),
                             ("UPLOAD_STARTED_AT", "needs.build.outputs.upload_started_at"),
                             ("WAIT_MINUTES", "needs.prepare.outputs.wait_minutes"),
                             ("POLL_SECONDS", "needs.prepare.outputs.poll_seconds")):
            self.assertIn(f"{name}: ${{{{ {output} }}}}", wait)
            self.assertIn(f'"${name}"', script)

    def test_no_workflow_uses_the_node20_cache_action(self) -> None:
        for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            with self.subTest(workflow=workflow.name):
                self.assertNotIn("actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830", workflow.read_text())

    def test_release_notes_never_block_a_release_that_does_not_use_them(self) -> None:
        # What's New is checked before the build, only when its switch is on.
        prepare = self.job("prepare")
        self.assertIn("UPLOAD_WHATS_NEW: ${{ steps.gates.outputs.whats_new }}", prepare)
        self.assertLess(prepare.index("asc_release.py --dry-run"), prepare.index("ios_release.py build-number"))
        # A tag without a RELEASE_NOTES.md section still gets a GitHub Release.
        self.assertIn("3) notes=(--generate-notes) ;;", self.job("github-release"))

    def test_release_notes_are_checked_before_the_build(self) -> None:
        prepare = self.job("prepare")
        start = prepare.index("      - name: Check release notes\n")
        end = prepare.find("\n      - ", start + 1)
        step = prepare[start:] if end == -1 else prepare[start:end]
        self.assertIn("if: github.event_name == 'push'", step)
        self.assertIn("TAG: ${{ github.ref_name }}", step)
        # Before App Store Connect is asked for a build number, so before any build.
        self.assertLess(start, prepare.index("ios_release.py build-number"))
        script = textwrap.dedent(step.split("run: |\n", 1)[1])

        def check(notes: str | None) -> int:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "scripts").mkdir()
                shutil.copy(ROOT / "scripts" / "release_notes.py", Path(tmp) / "scripts")
                if notes is not None:
                    (Path(tmp) / "RELEASE_NOTES.md").write_text(notes)
                result = subprocess.run(["bash", "-e", "-c", script], cwd=tmp, capture_output=True,
                                        text=True, env=dict(os.environ, TAG=TAG), check=False)
                return result.returncode

        self.assertEqual(check(f"## {TAG}\n\n- Fixes\n"), 0)
        self.assertEqual(check("## Unreleased\n\n- next\n"), 0)  # no section: generated notes
        self.assertEqual(check(None), 0)  # no RELEASE_NOTES.md at all
        self.assertEqual(check(f"## {TAG}\n\n## v1.0\n\n- old\n"), 1)  # empty section fails early
        self.assertEqual(check(f"## {TAG}\n\n- Fixes\n\n## {TAG}\n\n- Other\n"), 1)  # so does a duplicate

    def test_old_release_workflow_is_gone(self) -> None:
        self.assertFalse((ROOT / ".github" / "workflows" / "github-release.yml").exists())

    def test_scripts_run_from_the_command_line(self) -> None:
        for script in ("ios_release.py", "asc_release.py", "export_listing.py", "print_gates.py", "validate_catalog.py",
                       "redact_logs.py"):
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, str(HERE / script), "--help"],
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
