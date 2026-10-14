#!/usr/bin/env python3
"""Offline tests for ABYSM's iOS release switches, build waiting, listing and review.

No network: every App Store Connect call goes to an in-memory fake.
Run: python3 -m unittest discover -s scripts -p 'test_*.py'
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
import release_notes  # noqa: E402
import validate_catalog  # noqa: E402
from ios_release import ReleaseError, resolve_gates  # noqa: E402

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
              uploaded: float = STARTED + 60, app: str = APP, pre: str = "P1") -> dict:
    return {
        "type": "builds",
        "id": build_id,
        "attributes": {"version": number, "processingState": state, "expired": expired, "uploadedDate": iso(uploaded)},
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
        cases = {
            "other id": [{"id": "999", "attributes": {"bundleId": asc_release.DEFAULT_BUNDLE_ID}}],
            "missing": [],
            "prefix only": [{"id": APP, "attributes": {"bundleId": asc_release.DEFAULT_BUNDLE_ID + ".beta"}}],
            "ambiguous": [{"id": APP}, {"id": APP}],
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
    """Screenshot sets with a capacity, asset uploads and processing states."""

    def __init__(self, existing: int, *, states: list[str] | None = None) -> None:
        self.shots = [f"OLD{i}" for i in range(existing)]
        self.states = states or ["COMPLETE"]
        self.calls: list[tuple[str, str]] = []
        self.commits: list[dict] = []
        self.uploads = 0

    def get(self, path: str) -> dict:
        self.calls.append(("GET", path))
        if "/appStoreVersionLocalizations" in path and path.startswith("/appStoreVersions/"):
            return {"data": [{"id": "LOC", "attributes": {"locale": "en-US"}}]}
        if path.endswith("/appScreenshotSets") or "/appScreenshotSets?" in path:
            return {"data": [{"id": "SET", "attributes": {"screenshotDisplayType": "APP_IPHONE_67"}}]}
        if "/appScreenshotSets/SET/appScreenshots" in path:
            return {"data": [{"id": s} for s in self.shots]}
        if path.startswith("/appScreenshots/"):
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
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
        return {"data": {"id": new_id, "attributes": {"uploadOperations": [
            {"url": "https://upload.example/x", "offset": 0, "length": body["data"]["attributes"]["fileSize"],
             "method": "PUT", "requestHeaders": [{"name": "Content-Type", "value": "image/png"}]}]}}}

    def patch(self, path: str, body: dict) -> dict:
        self.calls.append(("PATCH", path))
        self.commits.append(body["data"]["attributes"])
        return {"data": body["data"]}

    def request(self, method: str, path: str, body: dict | None = None):
        self.calls.append((method, path))
        if method == "DELETE":
            self.shots.remove(path.rsplit("/", 1)[1])

    def upload_bytes(self, url: str, data: bytes, headers: dict, *, method: str = "PUT") -> None:
        self.calls.append(("UPLOAD", url))


class ScreenshotUploadTests(unittest.TestCase):
    def plan(self, tmp: str, count: int) -> list:
        return [("APP_IPHONE_67", [png(Path(tmp) / f"{i:02}.png", 2796, 1290) for i in range(count)])]

    def test_replaces_a_full_set_without_exceeding_capacity(self) -> None:
        client = ScreenshotUploadClient(existing=10)
        with tempfile.TemporaryDirectory() as tmp:
            quiet(asc_release.upload_screenshots, client, version_id="V1", locale="en-US",
                  plan=self.plan(tmp, 5), wait=lambda c, ids: None)
        self.assertEqual(len(client.shots), 5)
        self.assertTrue(all(s.startswith("NEW") for s in client.shots), client.shots)
        self.assertTrue(all(c["uploaded"] is True and len(c["sourceFileChecksum"]) == 32 for c in client.commits))

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


def metadata_tree(tmp: str, files: dict[str, str], locale: str = "en-US") -> Path:
    loc = Path(tmp) / "ios" / locale
    loc.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (loc / name).write_text(text)
    return Path(tmp)


class ListingTests(unittest.TestCase):
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


class ProductClient:
    """Review submissions, subscription versions and IAP states for product submission."""

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


def product_collections(unlock_state: str = "READY_TO_SUBMIT") -> dict[str, list[dict]]:
    return {
        asc_release.draft_submission_query(APP): [{"id": "SUB1"}],
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
    }


class ProductSubmissionTests(unittest.TestCase):
    INTENDED = {UNLOCK, "com.apoorvdarshan.Abysm.pass"}

    def test_submits_ready_catalog_products_only(self) -> None:
        client = ProductClient(product_collections())
        result = quiet(asc_release.submit_in_app_purchases, client, APP, intended_ids=self.INTENDED)
        self.assertEqual(result.submitted, 2)
        self.assertEqual(result.submission_id, "SUB1")
        items = [b for p, b in client.posts if p == "/reviewSubmissionItems"]
        self.assertEqual([b["data"]["relationships"]["subscriptionVersion"]["data"]["id"] for b in items], ["V1b"])
        iaps = [b for p, b in client.posts if p == "/inAppPurchaseSubmissions"]
        self.assertEqual([b["data"]["relationships"]["inAppPurchaseV2"]["data"]["id"] for b in iaps], ["IAP1"])

    def test_approved_unlock_is_never_resubmitted(self) -> None:
        client = ProductClient(product_collections(unlock_state="APPROVED"))
        result = quiet(asc_release.submit_in_app_purchases, client, APP, intended_ids={UNLOCK})
        self.assertEqual(result.submitted, 0)
        self.assertEqual(client.posts, [])

    def test_retry_skips_products_already_in_the_draft(self) -> None:
        collections = product_collections(unlock_state="APPROVED")
        collections[ITEMS] = [{"id": "I1", "relationships": {"subscriptionVersion": {"data": {"id": "V1b"}}}}]
        client = ProductClient(collections)
        result = quiet(asc_release.submit_in_app_purchases, client, APP, intended_ids=self.INTENDED)
        self.assertEqual((result.submitted, result.added_items, result.has_products), (1, False, True))
        self.assertEqual(client.posts, [])

    def test_failed_required_product_raises(self) -> None:
        client = ProductClient(product_collections())
        client.post = mock.Mock(side_effect=asc_release.AscHttpError(409, "conflict"))
        with self.assertRaises(asc_release.ProductSubmitError):
            quiet(asc_release.submit_in_app_purchases, client, APP, intended_ids={UNLOCK})

    def test_empty_catalog_submits_nothing(self) -> None:
        client = ProductClient(product_collections())
        result = quiet(asc_release.submit_in_app_purchases, client, APP, intended_ids=set())
        self.assertEqual(result.submitted, 0)
        self.assertEqual(client.posts, [])

    def test_submit_for_review_does_not_add_the_version_twice(self) -> None:
        collections = {ITEMS: [{"id": "I1", "relationships": {"appStoreVersion": {"data": {"id": "AV1"}}}}]}
        client = ProductClient(collections)
        quiet(asc_release.submit_for_review, client, APP, "AV1", "PREPARE_FOR_SUBMISSION", submission_id="SUB1")
        self.assertEqual([p for p, _ in client.posts], [])
        self.assertIn(("PATCH", "/reviewSubmissions/SUB1"), [(m, p) for m, p, _ in client.requests])
        self.assertTrue(asc_release.draft_holds_app_version(client, "SUB1"))
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

    def test_whats_new_without_text_fails(self) -> None:
        # The live 1.0 listing has no What's New; a release must add whats_new.txt first.
        if (asc_release.METADATA_DIR / "ios" / "en-US" / "whats_new.txt").exists():
            self.skipTest("whats_new.txt is present")
        code, output = self.run_cli({"UPLOAD_WHATS_NEW": "true"})
        self.assertEqual(code, 1)
        self.assertIn("whats_new.txt", output)

    def test_full_dry_run_with_repo_inputs(self) -> None:
        code, output = self.run_cli(
            {"UPLOAD_LISTING": "true", "UPLOAD_SCREENSHOTS": "true", "SUBMIT_IOS_REVIEW": "true"},
            "--build-id", "DRY-RUN", "--build-number", "3")
        self.assertEqual(code, 0, output)
        self.assertIn("no API calls", output)
        self.assertIn("screenshots=10", output)

    def test_live_run_requires_version_and_credentials(self) -> None:
        code, output = self.run_cli({"UPLOAD_LISTING": "true"}, dry_run=False)
        self.assertEqual(code, 1)
        self.assertIn("--version", output)
        code, output = self.run_cli(
            {"UPLOAD_LISTING": "true", "APP_STORE_CONNECT_API_KEY_ID": "", "APP_STORE_CONNECT_ISSUER_ID": "",
             "APP_STORE_CONNECT_API_KEY_P8": ""}, "--version", VERSION, dry_run=False)
        self.assertEqual(code, 1)
        self.assertIn("missing ASC credentials", output)


class FakeAsc:
    """App Store Connect stand-in for asc_release.main() (live path, no network)."""

    def __init__(self, *, state: str = "PREPARE_FOR_SUBMISSION", attached: str | None = "OLD",
                 revert_after_select: bool = False) -> None:
        self.state = state
        self.attached = attached
        self.revert_after_select = revert_after_select
        self.build_reads = 0
        self.calls: list[tuple[str, str]] = []

    def get(self, path: str) -> dict:
        self.calls.append(("GET", path))
        if path.startswith("/apps?"):
            return {"data": [{"id": APP, "attributes": {"bundleId": asc_release.DEFAULT_BUNDLE_ID}}]}
        if path.startswith(f"/apps/{APP}/appStoreVersions"):
            return {"data": [{"id": "V1", "attributes": {"versionString": VERSION, "appStoreState": self.state}}]}
        if path.startswith("/builds/B9"):
            return {"data": build_row("B9"), "included": [pre_row()]}
        if path == "/appStoreVersions/V1/build":
            self.build_reads += 1
            if self.revert_after_select and self.build_reads >= 2:
                return {"data": {"type": "builds", "id": "OLD"}}
            return {"data": {"type": "builds", "id": self.attached} if self.attached else None}
        if path.startswith(f"/apps/{APP}/reviewSubmissions"):
            return {"data": [{"id": "SUB1"}]}
        if path.startswith("/reviewSubmissions/SUB1/items"):
            return {"data": []}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, body: dict) -> dict:
        self.calls.append(("POST", path))
        return {"data": {"id": "ITEM"}}

    def patch(self, path: str, body: dict) -> dict:
        self.calls.append(("PATCH", path))
        return {"data": body["data"]}

    def request(self, method: str, path: str, body: dict | None = None):
        self.calls.append((method, path))
        if method == "PATCH" and path == "/appStoreVersions/V1/relationships/build":
            self.attached = body["data"]["id"]
        return None


class LiveSubmitFlowTests(unittest.TestCase):
    def run_main(self, fake: FakeAsc) -> tuple[int, mock.Mock]:
        products = mock.Mock(return_value=asc_release.ProductSubmitResult("SUB1", 0, False))
        argv = ["asc_release.py", "--version", VERSION, "--build-id", "B9", "--build-number", "3"]
        env = {k: v for k, v in os.environ.items() if k not in ASC_FLAGS}
        env["SUBMIT_IOS_REVIEW"] = "true"
        code = 0
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(asc_release, "client_from_environment", return_value=fake), \
                mock.patch.object(asc_release, "submit_in_app_purchases", products), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            try:
                asc_release.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, products

    def test_selects_rechecks_then_submits(self) -> None:
        fake = FakeAsc()
        code, products = self.run_main(fake)
        self.assertEqual(code, 0)
        calls = fake.calls
        select = calls.index(("PATCH", "/appStoreVersions/V1/relationships/build"))
        submit = calls.index(("PATCH", "/reviewSubmissions/SUB1"))
        reads = [i for i, c in enumerate(calls) if c == ("GET", "/appStoreVersions/V1/build")]
        build_checks = [i for i, c in enumerate(calls) if c[0] == "GET" and c[1].startswith("/builds/B9")]
        self.assertEqual(len(reads), 2, "selection must be read back and rechecked")
        self.assertTrue(select < reads[0] < reads[1] < submit)
        self.assertEqual(len(build_checks), 2)
        self.assertTrue(build_checks[1] < reads[1] < submit, "build must be re-verified just before submit")
        self.assertIn(("PATCH", "/appStoreVersions/V1"), calls)  # release type
        products.assert_called_once()

    def test_selection_changed_before_submit_aborts(self) -> None:
        fake = FakeAsc(revert_after_select=True)
        code, _ = self.run_main(fake)
        self.assertEqual(code, 1)
        self.assertNotIn(("PATCH", "/reviewSubmissions/SUB1"), fake.calls)

    def test_waiting_for_review_with_another_build_aborts(self) -> None:
        fake = FakeAsc(state="WAITING_FOR_REVIEW", attached="OTHER")
        code, products = self.run_main(fake)
        self.assertEqual(code, 1)
        products.assert_not_called()
        self.assertNotIn(("PATCH", "/reviewSubmissions/SUB1"), fake.calls)

    def test_waiting_for_review_with_this_build_is_idempotent(self) -> None:
        fake = FakeAsc(state="WAITING_FOR_REVIEW", attached="B9")
        code, products = self.run_main(fake)
        self.assertEqual(code, 0)
        products.assert_called_once()
        self.assertNotIn(("PATCH", "/appStoreVersions/V1/relationships/build"), fake.calls)

    def test_live_version_is_not_submitted(self) -> None:
        fake = FakeAsc(state="READY_FOR_SALE")
        code, products = self.run_main(fake)
        self.assertEqual(code, 1)
        products.assert_not_called()
        self.assertNotIn(("PATCH", "/appStoreVersions/V1/relationships/build"), fake.calls)


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

    def test_build_logs_are_redacted_before_upload(self) -> None:
        build = self.job("build")
        self.assertIn("name: ios-release-logs-${{ github.run_id }}-${{ github.run_attempt }}", build)
        program = re.search(r"perl -pi -e '([^']+)'", build)
        self.assertIsNotNone(program)
        self.assertLess(build.index("perl -pi"), build.index("actions/upload-artifact"))
        if shutil.which("perl") is None:
            self.skipTest("perl is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "archive.log"
            log.write_text("-authenticationKeyID AB1.C2 -authenticationKeyIssuerID 69a6-de7f\nAB1XC2\n")
            env = dict(os.environ, ASC_KEY_ID="AB1.C2", ASC_ISSUER_ID="69a6-de7f")
            subprocess.run(["perl", "-pi", "-e", program.group(1), str(log)], env=env, check=True)
            self.assertEqual(
                log.read_text(),
                "-authenticationKeyID <ASC_KEY_ID> -authenticationKeyIssuerID <ASC_ISSUER_ID>\nAB1XC2\n",
            )

    def test_release_notes_never_block_a_release_that_does_not_use_them(self) -> None:
        # What's New is checked before the build, only when its switch is on.
        prepare = self.job("prepare")
        self.assertIn("UPLOAD_WHATS_NEW: ${{ steps.gates.outputs.whats_new }}", prepare)
        self.assertLess(prepare.index("asc_release.py --dry-run"), prepare.index("ios_release.py build-number"))
        # A tag without a RELEASE_NOTES.md section still gets a GitHub Release.
        self.assertIn("3) notes=(--generate-notes) ;;", self.job("github-release"))

    def test_old_release_workflow_is_gone(self) -> None:
        self.assertFalse((ROOT / ".github" / "workflows" / "github-release.yml").exists())

    def test_scripts_run_from_the_command_line(self) -> None:
        for script in ("ios_release.py", "asc_release.py", "export_listing.py", "print_gates.py", "validate_catalog.py"):
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, str(HERE / script), "--help"],
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
