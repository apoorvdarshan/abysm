#!/usr/bin/env python3
"""Offline tests for ABYSM's iOS release switches, build waiting, listing and review.

No network: every App Store Connect call goes to an in-memory App Store Connect
behind a fake `asc` (FakeAsc), and the asc runner itself (asc_cli.py) runs with
an injected process runner. Also checks that scripts/test-ios.sh shuts the
simulator down between the unit and UI tests, against a fake xcrun (no simulator).
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
import hashlib
import io
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))

import asc_cli  # noqa: E402
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
APP = asc_release.ASC_APP_ID
BUNDLE = asc_release.DEFAULT_BUNDLE_ID
ALL_ON = {
    "IOS_RELEASE_AUTOMATION": "true",
    "IOS_CREATE_VERSION": "true",
    "IOS_UPLOAD_BUILD": "true",
    "IOS_UPLOAD_LISTING": "true",
    "IOS_UPLOAD_WHATS_NEW": "true",
    "IOS_UPLOAD_SCREENSHOTS": "true",
    "IOS_UPLOAD_CREATIVE_ASSETS": "true",
    "IOS_SUBMIT_REVIEW": "true",
    "IOS_PUBLIC_RELEASE": "true",
}
OPS = ("create_version", "upload_build", "listing", "whats_new", "screenshots", "creative", "submit", "public_release")
ASC_FLAGS = {"UPLOAD_LISTING", "UPLOAD_WHATS_NEW", "UPLOAD_SCREENSHOTS", "UPLOAD_CREATIVE_ASSETS", "SUBMIT_IOS_REVIEW",
             "PUBLIC_RELEASE", "CREATE_IOS_VERSION"}


def quiet(fn, *args, **kwargs):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def gates(env: dict[str, str], *, event: str = "push", ref: str = TAG, version: str = VERSION) -> dict:
    return resolve_gates(env, event=event, ref_name=ref, marketing_version=version)


def flag(call: tuple[str, ...], name: str) -> str:
    """The value passed with `name` in one asc call."""
    return call[call.index(name) + 1]


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

    def test_create_version_needs_only_the_master_switch(self) -> None:
        result = gates({"IOS_RELEASE_AUTOMATION": "true", "IOS_CREATE_VERSION": "true"})
        self.assertTrue(result["create_version"])
        self.assertFalse(result["build"])
        self.assertFalse(result["asc"])
        self.assertFalse(gates({"IOS_CREATE_VERSION": "true"})["create_version"])
        self.assertFalse(gates(ALL_ON, event="workflow_dispatch", ref="main")["create_version"])
        with self.assertRaisesRegex(ReleaseError, "IOS_CREATE_VERSION"):
            gates({"IOS_CREATE_VERSION": "sometimes"})

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

    def test_creative_assets_are_a_store_operation_of_their_own(self) -> None:
        result = gates({"IOS_RELEASE_AUTOMATION": "true", "IOS_UPLOAD_CREATIVE_ASSETS": "true"})
        self.assertTrue(result["creative"])
        self.assertTrue(result["asc"])
        self.assertFalse(result["build"])
        self.assertFalse(result["screenshots"])
        self.assertFalse(gates({"IOS_UPLOAD_CREATIVE_ASSETS": "true"})["creative"])  # the master switch is off
        self.assertFalse(gates(ALL_ON, event="workflow_dispatch", ref="main")["creative"])
        with self.assertRaisesRegex(ReleaseError, "IOS_UPLOAD_CREATIVE_ASSETS"):
            gates({"IOS_UPLOAD_CREATIVE_ASSETS": "sometimes"})

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


COMPLIANCE_PBX = """
		AAA /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
{debug}				PRODUCT_BUNDLE_IDENTIFIER = com.apoorvdarshan.Abysm;
			}};
			name = Debug;
		}};
		BBB /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
{release}				PRODUCT_BUNDLE_IDENTIFIER = {release_bundle};
			}};
			name = Release;
		}};
		CCC /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
{other}				PRODUCT_BUNDLE_IDENTIFIER = com.apoorvdarshan.AbysmTests;
			}};
			name = Release;
		}};
"""
NO = "INFOPLIST_KEY_ITSAppUsesNonExemptEncryption = NO"
YES = "INFOPLIST_KEY_ITSAppUsesNonExemptEncryption = YES"
CODE = "INFOPLIST_KEY_ITSEncryptionExportComplianceCode = ABC123"
PLIST_FILE = "INFOPLIST_FILE = Abysm/Info.plist"


class ExportComplianceTests(unittest.TestCase):
    """ITSAppUsesNonExemptEncryption must be declared, or App Store Connect asks about every build."""

    def project(self, debug: list[str], release: list[str] | None = None, plist: dict | None = None, *,
                other: tuple[str, ...] = ("INFOPLIST_KEY_ITSAppUsesNonExemptEncryption = YES",),
                release_bundle: str = "com.apoorvdarshan.Abysm") -> Path:
        """A temporary project (app Debug/Release + a test target with `other` settings) and its Abysm/Info.plist."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        if plist is not None:
            (root / "Abysm").mkdir()
            (root / "Abysm" / "Info.plist").write_bytes(plistlib.dumps(plist))
        lines = lambda settings: "".join(f"\t\t\t\t{line};\n" for line in settings)  # noqa: E731
        pbxproj = root / "Abysm.xcodeproj" / "project.pbxproj"
        pbxproj.parent.mkdir()
        pbxproj.write_text(COMPLIANCE_PBX.format(debug=lines(debug), release=lines(debug if release is None else release),
                                                 other=lines(other), release_bundle=release_bundle))
        return pbxproj

    def check(self, *args, **kwargs) -> str:
        return ios_release.check_export_compliance(self.project(*args, **kwargs))

    def info_plist(self, values: dict) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "Abysm.app" / "Info.plist"
        path.parent.mkdir()
        path.write_bytes(plistlib.dumps({"CFBundleIdentifier": ios_release.BUNDLE_ID, **values},
                                        fmt=plistlib.FMT_BINARY))  # archived apps carry binary plists
        return path

    def test_the_real_app_declares_no_non_exempt_encryption(self) -> None:
        self.assertEqual(sorted(ios_release.app_build_configurations()), ["Debug", "Release"])
        self.assertEqual(ios_release.check_export_compliance(), "NO")
        with (ROOT / "Abysm" / "Info.plist").open("rb") as handle:
            self.assertIs(plistlib.load(handle)[ios_release.ENCRYPTION_KEY], False)

    def test_no_from_the_build_setting_or_the_info_plist_passes(self) -> None:
        self.assertEqual(self.check([NO]), "NO")
        self.assertEqual(self.check([PLIST_FILE], plist={"ITSAppUsesNonExemptEncryption": False}), "NO")
        self.assertEqual(self.check([NO, PLIST_FILE], plist={"ITSAppUsesNonExemptEncryption": False}), "NO")
        self.assertEqual(self.check(['INFOPLIST_FILE = "$(SRCROOT)/Abysm/Info.plist"'],
                                    plist={"ITSAppUsesNonExemptEncryption": False}), "NO")

    def test_missing_declaration_fails_before_the_build(self) -> None:
        for release, missing in ((None, "Debug, Release"), ([NO, PLIST_FILE], "Debug")):
            with self.subTest(release=release), self.assertRaisesRegex(
                    ReleaseError, rf"the app target \(com\.apoorvdarshan\.Abysm\) does not declare export "
                                  rf"compliance \({missing}\)"):
                self.check([PLIST_FILE], release, plist={"UILaunchScreen": {}})
        with self.assertRaisesRegex(ReleaseError, "does not declare export compliance"):
            self.check(["INFOPLIST_KEY_CFBundleDisplayName = ABYSM"])

    def test_a_value_set_only_for_debug_or_only_on_another_target_fails(self) -> None:
        # Debug alone, or Release alone, never stands in for the other configuration.
        with self.assertRaisesRegex(ReleaseError, r"does not declare export compliance \(Release\)"):
            self.check([NO], [])
        with self.assertRaisesRegex(ReleaseError, r"does not declare export compliance \(Debug\)"):
            self.check([], [NO])
        # Another target's answer (here the tests' Release configuration) is not the app's.
        with self.assertRaisesRegex(ReleaseError, r"does not declare export compliance \(Debug, Release\)"):
            self.check([], other=(NO,))
        self.assertEqual(self.check([NO], other=(YES,)), "NO")  # the tests' YES without a code is ignored

    def test_both_app_configurations_must_exist(self) -> None:
        # A Release configuration that does not build the app's bundle id cannot be
        # checked, so a Debug-only answer never passes for it.
        for bundle in ("$(APP_BUNDLE_ID)", "com.apoorvdarshan.Abysm.dev"):
            with self.subTest(bundle=bundle), self.assertRaisesRegex(
                    ReleaseError, r"could not find the Debug and Release configurations .*found \['Debug'\]"):
                self.check([NO], release_bundle=bundle)
        with self.assertRaisesRegex(ReleaseError, "no build configuration builds com.example.Other"):
            ios_release.check_export_compliance(self.project([NO]), bundle_id="com.example.Other")

    def test_yes_needs_the_compliance_code(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "needs ITSEncryptionExportComplianceCode"):
            self.check([YES])
        with self.assertRaisesRegex(ReleaseError, "missing in .*: Release"):
            self.check([YES, CODE], [YES])
        self.assertEqual(self.check([YES, CODE]), "YES")
        self.assertEqual(self.check([PLIST_FILE], plist={"ITSAppUsesNonExemptEncryption": True,
                                                         "ITSEncryptionExportComplianceCode": "ABC123"}), "YES")

    def test_mixed_or_unknown_values_fail(self) -> None:
        cases = {
            "Debug NO, Release YES": ([NO], [YES, CODE], None),
            "build setting and Info.plist disagree": ([NO, PLIST_FILE], None, {"ITSAppUsesNonExemptEncryption": True}),
            "unknown build setting": (["INFOPLIST_KEY_ITSAppUsesNonExemptEncryption = maybe"], None, None),
            "Info.plist string instead of a Boolean": ([PLIST_FILE], None, {"ITSAppUsesNonExemptEncryption": "NO"}),
        }
        for label, (debug, release, plist) in cases.items():
            with self.subTest(label), self.assertRaisesRegex(ReleaseError, "must be one NO or YES"):
                self.check(debug, release, plist=plist)

    def test_an_info_plist_that_cannot_be_read_fails(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "cannot read"):
            self.check([NO, PLIST_FILE])  # the file does not exist
        with self.assertRaisesRegex(ReleaseError, "cannot resolve INFOPLIST_FILE"):
            self.check([NO, "INFOPLIST_FILE = $(TARGET_NAME)/Info.plist"])

    def test_the_archived_info_plist_is_checked_the_same_way(self) -> None:
        check = ios_release.check_bundle_export_compliance
        self.assertEqual(check(self.info_plist({"ITSAppUsesNonExemptEncryption": False})), "NO")
        self.assertEqual(check(self.info_plist({"ITSAppUsesNonExemptEncryption": True,
                                                "ITSEncryptionExportComplianceCode": "ABC123"})), "YES")
        for values, message in (({}, r"the archived Abysm.app does not declare"),
                                ({"ITSAppUsesNonExemptEncryption": True}, "needs ITSEncryptionExportComplianceCode"),
                                ({"ITSAppUsesNonExemptEncryption": "false"}, "must be one NO or YES")):
            with self.subTest(values=values), self.assertRaisesRegex(ReleaseError, message):
                check(self.info_plist(values))

    def test_the_command_line_check_fails_the_step(self) -> None:
        script = str(HERE / "ios_release.py")
        good = self.info_plist({"ITSAppUsesNonExemptEncryption": False})
        bad = self.info_plist({})
        result = subprocess.run([sys.executable, script, "export-compliance", "--info-plist", str(good)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ITSAppUsesNonExemptEncryption = NO (no non-exempt encryption)", result.stdout)
        result = subprocess.run([sys.executable, script, "export-compliance", "--info-plist", str(bad)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("error: the archived Abysm.app does not declare export compliance", result.stderr)
        result = subprocess.run([sys.executable, script, "export-compliance"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gates_check_it_only_when_this_run_builds(self) -> None:
        for env, builds in (({"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF_NAME": "main"}, True),
                            ({"GITHUB_EVENT_NAME": "push", "GITHUB_REF_NAME": TAG, "IOS_RELEASE_AUTOMATION": "true",
                              "IOS_UPLOAD_BUILD": "true"}, True),
                            ({"GITHUB_EVENT_NAME": "push", "GITHUB_REF_NAME": TAG}, False)):
            missing = mock.patch.object(ios_release, "check_export_compliance",
                                        side_effect=ReleaseError("Abysm does not declare export compliance"))
            with self.subTest(env=env), missing as check, \
                    mock.patch.object(ios_release, "project_marketing_version", return_value=VERSION), \
                    mock.patch.dict(os.environ, env, clear=True), redirect_stdout(io.StringIO()), \
                    redirect_stderr(io.StringIO()) as err:
                if builds:
                    with self.assertRaises(SystemExit):
                        ios_release.main(["gates"])
                    self.assertIn("does not declare export compliance", err.getvalue())
                else:
                    ios_release.main(["gates"])
                    check.assert_not_called()
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF_NAME": "main"},
                             clear=True), redirect_stdout(out):
            ios_release.main(["gates"])
        self.assertIn("export compliance: ITSAppUsesNonExemptEncryption = NO", out.getvalue())


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


def png_header(color_type: int = 2, *, trns: bool = False, width: int = 16, height: int = 16) -> bytes:
    """A PNG signature and IHDR (plus an optional tRNS chunk) with the given colour type and size."""
    import zlib

    def chunk(kind: bytes, body: bytes) -> bytes:
        return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")

    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, color_type, 0, 0, 0])
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + (chunk(b"tRNS", b"\x00\x00") if trns else b"") + chunk(b"IDAT", b"x")


def jpeg_header(width: int, height: int) -> bytes:
    """A JPEG with an APP0 segment and a baseline SOF0 frame header of the given size."""
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + bytes(9)
    sof0 = b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + bytes(12)
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def asc_error(code: int) -> asc_cli.AscError:
    return asc_cli.AscError(("builds", "list"), code, "failed")


class FakeClock:
    def __init__(self, start: float) -> None:
        self.time = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.time += seconds


class SequenceAsc:
    """Returns queued `asc builds list` payloads (or raises queued exceptions) per call."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def run(self, *args: str, **_: object) -> dict:
        self.calls.append(args)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, BaseException):
            raise item
        return item


def wait(client: SequenceAsc, clock: FakeClock, *, minutes: int = 120, transient=None) -> dict:
    with redirect_stdout(io.StringIO()):
        return ios_release.wait_for_build(
            client, app_id=APP, marketing_version=VERSION, build_number="3", uploaded_after=STARTED,
            deadline=STARTED + minutes * 60, poll_seconds=30, now=clock.now, sleep=clock.sleep,
            is_transient=transient,
        )


class WaitForBuildTests(unittest.TestCase):
    def test_waits_through_missing_and_processing_then_returns_build(self) -> None:
        client = SequenceAsc([
            {"data": []},
            {"data": [build_row(state="PROCESSING")], "included": [pre_row()]},
            {"data": [build_row()], "included": [pre_row()]},
        ])
        clock = FakeClock(STARTED + 120)
        self.assertEqual(wait(client, clock)["id"], "B1")
        self.assertEqual(clock.sleeps, [30, 30])
        query = client.calls[0]
        self.assertEqual(query[:2], ("builds", "list"))
        self.assertEqual((flag(query, "--app"), flag(query, "--build-number"), flag(query, "--platform")), (APP, "3", "IOS"))
        # Every build with this number, whatever its state, with its app and version.
        self.assertEqual(flag(query, "--processing-state"), "all")
        self.assertEqual(flag(query, "--include"), "preReleaseVersion,app")

    def test_times_out_without_using_another_build(self) -> None:
        client = SequenceAsc([{"data": [build_row(state="PROCESSING")], "included": [pre_row()]}])
        clock = FakeClock(STARTED)
        with self.assertRaisesRegex(ReleaseError, "timed out"):
            wait(client, clock, minutes=10)
        self.assertLessEqual(clock.time, STARTED + 10 * 60 + 30)

    def test_ready_build_after_the_deadline_is_still_a_timeout(self) -> None:
        client = SequenceAsc([{"data": [build_row()], "included": [pre_row()]}])
        clock = FakeClock(STARTED + 121 * 60)
        with self.assertRaisesRegex(ReleaseError, "timed out"):
            wait(client, clock)
        self.assertEqual(client.calls, [], "must not poll once the budget is spent")

    def test_processing_failure_stops(self) -> None:
        for state in ("FAILED", "INVALID"):
            client = SequenceAsc([{"data": [build_row(state=state)], "included": [pre_row()]}])
            with self.subTest(state=state), self.assertRaisesRegex(ReleaseError, state):
                wait(client, FakeClock(STARTED))

    def test_expired_build_is_rejected(self) -> None:
        client = SequenceAsc([{"data": [build_row(expired=True)], "included": [pre_row()]}])
        with self.assertRaisesRegex(ReleaseError, "expired"):
            wait(client, FakeClock(STARTED))

    def test_ambiguous_match_stops(self) -> None:
        client = SequenceAsc([{"data": [build_row("B1"), build_row("B2")], "included": [pre_row()]}])
        with self.assertRaisesRegex(ReleaseError, "ambiguous"):
            wait(client, FakeClock(STARTED))

    def test_older_upload_is_never_substituted(self) -> None:
        client = SequenceAsc([{"data": [build_row(uploaded=STARTED - 3600)], "included": [pre_row()]}])
        with self.assertRaisesRegex(ReleaseError, "older build"):
            wait(client, FakeClock(STARTED))

    def test_build_without_an_upload_time_is_never_accepted(self) -> None:
        # Fail closed: it could be an older build with the same number.
        for missing in (None, ""):
            client = SequenceAsc([{"data": [build_row(uploaded=missing)], "included": [pre_row()]}])
            with self.subTest(uploaded=missing), self.assertRaisesRegex(ReleaseError, "timed out"):
                wait(client, FakeClock(STARTED), minutes=10)
        state, message, build = ios_release.evaluate_builds(
            {"data": [build_row(uploaded=None)], "included": [pre_row()]},
            app_id=APP, marketing_version=VERSION, build_number="3", uploaded_after=STARTED)
        self.assertEqual((state, build), (ios_release.BuildState.WAITING, None))
        self.assertIn("uploadedDate", message)

    def test_upload_time_reported_later_is_accepted(self) -> None:
        client = SequenceAsc([
            {"data": [build_row(uploaded=None)], "included": [pre_row()]},
            {"data": [build_row()], "included": [pre_row()]},
        ])
        clock = FakeClock(STARTED)
        self.assertEqual(wait(client, clock)["id"], "B1")
        self.assertEqual(clock.sleeps, [30])

    def test_unreadable_upload_time_stops(self) -> None:
        for bad in ("yesterday", 1_800_000_000):
            client = SequenceAsc([{"data": [build_row(uploaded=None)], "included": [pre_row()]}])
            client.responses[0]["data"][0]["attributes"]["uploadedDate"] = bad
            with self.subTest(uploaded=bad), self.assertRaisesRegex(ReleaseError, "unreadable uploadedDate"):
                wait(client, FakeClock(STARTED))

    def test_other_versions_and_platforms_are_ignored(self) -> None:
        other_version = build_row("BX", pre="P2")
        other_platform = build_row("BY", pre="P3")
        client = SequenceAsc([
            {"data": [other_version, other_platform], "included": [pre_row("P2", "1.0"), pre_row("P3", VERSION, "MAC_OS")]},
            {"data": [other_version, build_row("B1")], "included": [pre_row("P2", "1.0"), pre_row()]},
        ])
        self.assertEqual(wait(client, FakeClock(STARTED))["id"], "B1")

    def test_build_from_another_app_is_a_mismatch(self) -> None:
        client = SequenceAsc([{"data": [build_row(app="OTHER")], "included": [pre_row()]}])
        with self.assertRaisesRegex(ReleaseError, "another app"):
            wait(client, FakeClock(STARTED))

    def test_transient_errors_are_retried_and_others_raise(self) -> None:
        client = SequenceAsc([asc_error(63), {"data": [build_row()], "included": [pre_row()]}])
        with redirect_stderr(io.StringIO()):
            build = wait(client, FakeClock(STARTED), transient=ios_release.is_transient_error)
        self.assertEqual(build["id"], "B1")
        fatal = SequenceAsc([asc_error(3)])
        with self.assertRaises(asc_cli.AscError):
            wait(fatal, FakeClock(STARTED), transient=ios_release.is_transient_error)


class TransientErrorTests(unittest.TestCase):
    def test_retry_rule_follows_asc_exit_codes(self) -> None:
        # asc exits 18 for HTTP 408, 39 for 429, 60-99 for any 5xx and 124 when the call ran out of time.
        for code in (18, 39, 60, 62, 63, 99, 124):
            with self.subTest(code=code):
                self.assertTrue(ios_release.is_transient_error(asc_error(code)))
        # Generic, usage, auth, not found, conflict, read-only refusal, other 4xx, unverified or missing asc.
        for code in (1, 2, 3, 4, 5, 6, 10, 32, 126, 127):
            with self.subTest(code=code):
                self.assertFalse(ios_release.is_transient_error(asc_error(code)))
        for exc in (ValueError("bad"), ReleaseError("mismatch"), SystemExit(1), ConnectionResetError("reset")):
            with self.subTest(exc=repr(exc)):
                self.assertFalse(ios_release.is_transient_error(exc))

    def test_network_drops_reported_as_exit_1_are_retried(self) -> None:
        for detail in ('Get "https://api.appstoreconnect.apple.com/v1/builds": read tcp: connection reset by peer',
                       "dial tcp: lookup api.appstoreconnect.apple.com: no such host",
                       "net/http: TLS handshake timeout", "unexpected EOF",
                       'Get "https://api.appstoreconnect.apple.com/v1/builds": EOF'):
            with self.subTest(detail=detail):
                self.assertTrue(ios_release.is_transient_error(asc_cli.AscError(("builds", "list"), 1, detail)))
        for detail in ("invalid character '<' looking for beginning of value", "build not found"):
            with self.subTest(detail=detail):
                self.assertFalse(ios_release.is_transient_error(asc_cli.AscError(("builds", "list"), 1, detail)))
        # The same message with another exit code keeps that code's rule.
        self.assertFalse(ios_release.is_transient_error(asc_cli.AscError(("builds", "list"), 3, "connection reset")))


class AscRunnerTests(unittest.TestCase):
    """scripts/store/asc_cli.py: the one place asc runs."""

    ENV = {
        "APP_STORE_CONNECT_API_KEY_ID": "TESTKEY0001",
        "APP_STORE_CONNECT_ISSUER_ID": "00000000-test-4000-8000-issuer000001",
        "APP_STORE_CONNECT_API_KEY_P8": "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----",
        "ASC_PROFILE": "personal",
        "ASC_CONFIG_PATH": "/home/me/.asc/config.json",
    }

    def run_once(self, *, returncode: int = 0, stdout: str = '{"data": []}', stderr: str = "", read_only=False, env=None):
        seen: dict = {}

        def runner(argv, **kwargs):
            seen["argv"], seen["env"] = argv, kwargs["env"]
            return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)

        with mock.patch.dict(os.environ, env or self.ENV, clear=True):
            result = asc_cli.Asc(binary="asc", read_only=read_only, runner=runner).run("apps", "view", "--id", APP)
        return result, seen

    def test_credentials_come_from_the_release_secrets_and_nothing_else(self) -> None:
        result, seen = self.run_once()
        self.assertEqual(result, {"data": []})
        self.assertEqual(seen["argv"], ["asc", "apps", "view", "--id", APP, "--output", "json"])
        env = seen["env"]
        self.assertEqual(env["ASC_KEY_ID"], "TESTKEY0001")
        self.assertEqual(env["ASC_ISSUER_ID"], self.ENV["APP_STORE_CONNECT_ISSUER_ID"])
        self.assertIn("\nabc\n", env["ASC_PRIVATE_KEY"])
        for name in ("ASC_PROFILE", "ASC_CONFIG_PATH"):
            self.assertNotIn(name, env)
        for name, value in (("ASC_BYPASS_KEYCHAIN", "1"), ("ASC_TELEMETRY_DISABLED", "1"), ("DO_NOT_TRACK", "1"),
                            ("ASC_SKILLS_AUTO_CHECK", "0"), ("ASC_STRICT_AUTH", "1"), ("ASC_MAX_RETRIES", "5")):
            self.assertEqual(env[name], value, name)
        self.assertNotIn("ASC_READ_ONLY", env)

    def test_read_only_from_the_caller_or_the_job(self) -> None:
        _, seen = self.run_once(read_only=True)
        self.assertEqual(seen["env"]["ASC_READ_ONLY"], "1")
        _, seen = self.run_once(env={**self.ENV, "ASC_READ_ONLY": "1"})
        self.assertEqual(seen["env"]["ASC_READ_ONLY"], "1")
        # The scripts ask for it where nothing may be written.
        env = {name: self.ENV[name] for name in ("APP_STORE_CONNECT_API_KEY_ID", "APP_STORE_CONNECT_ISSUER_ID",
                                                 "APP_STORE_CONNECT_API_KEY_P8")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(asc_release.asc_from_environment(read_only=True).read_only)
            self.assertFalse(asc_release.asc_from_environment().read_only)

    def test_failures_keep_the_exit_code_and_hide_the_ids(self) -> None:
        stderr = f"401 for key {self.ENV['APP_STORE_CONNECT_API_KEY_ID']} issuer {self.ENV['APP_STORE_CONNECT_ISSUER_ID']}"
        with self.assertRaises(asc_cli.AscError) as caught:
            self.run_once(returncode=3, stderr=stderr)
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertNotIn("TESTKEY0001", str(caught.exception))
        self.assertNotIn("issuer000001", str(caught.exception))
        with self.assertRaises(asc_cli.AscError):
            self.run_once(stdout="not json")
        # The release step turns it into a readable error that keeps the exit code.
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit):
            asc_release.call(mock.Mock(run=mock.Mock(side_effect=asc_cli.AscError(("apps", "view"), 3, "unauthorized"))),
                             "apps", "view")
        self.assertIn("asc apps view failed (exit 3): unauthorized", err.getvalue())

    def test_missing_credentials_stop_before_asc_runs(self) -> None:
        for missing in ("APP_STORE_CONNECT_API_KEY_ID", "APP_STORE_CONNECT_ISSUER_ID", "APP_STORE_CONNECT_API_KEY_P8"):
            env = {name: value for name, value in self.ENV.items() if name != missing}
            err = io.StringIO()
            with self.subTest(missing=missing), mock.patch.dict(os.environ, env, clear=True), \
                    redirect_stderr(err), self.assertRaises(SystemExit):
                asc_release.asc_from_environment()
            self.assertIn("missing ASC credentials", err.getvalue())

    def test_install_accepts_only_the_pinned_binary(self) -> None:
        good = b"pinned-binary"
        with mock.patch.dict(asc_cli.ASC_SHA256, {"linux_amd64": hashlib.sha256(good).hexdigest()}):
            with tempfile.TemporaryDirectory() as tmp:
                opener = lambda url, timeout: io.BytesIO(good)  # noqa: E731
                target = quiet(asc_cli.install, Path(tmp), key="linux_amd64", opener=opener)
                self.assertEqual(target.read_bytes(), good)
                self.assertTrue(os.access(target, os.X_OK))
                bad = lambda url, timeout: io.BytesIO(b"tampered")  # noqa: E731
                with self.assertRaises(SystemExit):
                    quiet(asc_cli.install, Path(tmp) / "other", key="linux_amd64", opener=bad)
                self.assertFalse((Path(tmp) / "other" / "asc").exists())

    def test_the_pin_is_one_exact_release_with_both_ci_platforms(self) -> None:
        self.assertEqual(asc_cli.ASC_VERSION, "5.15.0")
        self.assertEqual(asc_cli.ASC_SHA256, {
            "linux_amd64": "614ae3190938f4826c8cfbbb836a1926f765963614c17fdeb86750883f71aa70",
            "macOS_arm64": "29b3f747acd94d1dc49884f4c0a7404181ec058c635d0ce20fc4202c930edf22",
        })
        self.assertEqual(asc_cli.platform_key("Linux", "x86_64"), "linux_amd64")
        self.assertEqual(asc_cli.platform_key("Darwin", "arm64"), "macOS_arm64")
        with self.assertRaises(SystemExit):
            asc_cli.platform_key("Windows", "x86_64")

    def test_only_the_pinned_binary_receives_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "asc"
            binary.write_bytes(b"pinned-binary")
            pinned = {asc_cli.platform_key(): hashlib.sha256(b"pinned-binary").hexdigest()}
            with mock.patch.dict(asc_cli.ASC_SHA256, pinned), mock.patch.object(asc_cli.shutil, "which", return_value=str(binary)):
                self.assertEqual(asc_cli.verified_binary("asc"), str(binary))
                binary.write_bytes(b"something else")
                with self.assertRaises(asc_cli.AscError) as caught:
                    asc_cli.verified_binary("asc")
                self.assertEqual(caught.exception.exit_code, 126)
                # A real run checks the binary before anything is executed.
                with mock.patch.object(asc_cli.subprocess, "run") as run, self.assertRaises(asc_cli.AscError):
                    asc_cli.Asc().run("apps", "view", "--id", APP)
                run.assert_not_called()
            with mock.patch.object(asc_cli.shutil, "which", return_value=None), self.assertRaises(asc_cli.AscError):
                asc_cli.verified_binary("asc")
        # No environment variable can point the release at another executable.
        with mock.patch.dict(os.environ, {"ASC_BIN": "/tmp/evil"}):
            self.assertEqual(asc_cli.Asc().binary, "asc")

    def test_alpha_is_detected_the_way_asc_refuses_it(self) -> None:
        cases = {"rgb": (png_header(2), False), "rgba": (png_header(6), True), "gray-alpha": (png_header(4), True),
                 "rgb-trns": (png_header(2, trns=True), True), "jpeg": (b"\xff\xd8\xff\xe0rest", False)}
        with tempfile.TemporaryDirectory() as tmp:
            for name, (content, expected) in cases.items():
                path = Path(tmp) / name
                path.write_bytes(content)
                with self.subTest(name=name):
                    self.assertEqual(asc_cli.image_has_alpha(path), expected)

    def test_a_leading_at_sign_is_escaped(self) -> None:
        self.assertEqual(asc_release.asc_value("@apoorvcodes on Instagram"), "@@apoorvcodes on Instagram")
        self.assertEqual(asc_release.asc_value("Dive the deep sea"), "Dive the deep sea")


# asc commands that change App Store Connect.
MUTATIONS = {
    ("versions", "create"), ("versions", "update"), ("versions", "attach-build"), ("localizations", "update"),
    ("screenshots", "upload"), ("asset-library", "images", "upload"), ("localizations", "placements", "create"),
    ("localizations", "placements", "swap"), ("review", "submissions-create"), ("review", "items-add"),
    ("review", "submissions-submit"),
}
# Review item type -> the relationship the item fills.
ITEM_TYPES = {"appStoreVersions": "appStoreVersion", "subscriptionVersions": "subscriptionVersion",
              "inAppPurchaseVersions": "inAppPurchaseVersion", "appAssetLibraryImages": "appAssetLibraryImage"}
DISPLAY_TYPES = {device: display for display, device in asc_release.DEVICE_TYPES.items()}

UNLOCK = "com.apoorvdarshan.Abysm.unlockdeep"
IPHONE = "APP_IPHONE_67"
IPAD = "APP_IPAD_PRO_3GEN_129"
REPO_TEXT = {"description.txt": "D", "keywords.txt": "k", "whats_new.txt": "Fixes", "subtitle.txt": "Sub"}
LIVE_TEXT = {"description": "D", "keywords": "k", "whatsNew": "Fixes"}
LIVE_INFO = {"subtitle": "Sub"}


def is_write(call: tuple[str, ...]) -> bool:
    return call[:2] in MUTATIONS or call[:3] in MUTATIONS


def review_item(item_id: str, relation: str, related: str) -> dict:
    """A review submission item the way asc lists it: unrelated relationships carry an empty id."""
    relationships = {name: {"data": {"type": "", "id": ""}} for name in asc_release.ITEM_RELATIONSHIPS}
    item_type = next(kind for kind, name in ITEM_TYPES.items() if name == relation)
    relationships[relation] = {"data": {"type": item_type, "id": related}}
    return {"type": "reviewSubmissionItems", "id": item_id, "relationships": relationships}


def items_added(fake: "FakeAsc") -> list[tuple[str, str]]:
    """(item type, item id) of every `asc review items-add`, in order."""
    return [(flag(c, "--item-type"), flag(c, "--item-id")) for c in fake.calls if c[:2] == ("review", "items-add")]


class FakeAsc:
    """App Store Connect behind `asc`, for asc_release, ios_release and export_listing (no network).

    One app (the pinned ABYSM record) with the iOS version V1 for VERSION next to
    `other_versions`, its App Info records, localizations for `locales`,
    screenshot sets, the build B9 this run uploaded, draft review submissions,
    the catalog's products and the Asset Library. Writes change that state the
    way App Store Connect does, so a second run sees what the first one did.
    open(read_only=True) stands in for asc_from_environment(read_only=True):
    every write is then refused with exit 6 before anything changes, like asc
    with ASC_READ_ONLY.
    """

    def __init__(
        self,
        *,
        state: str = "PREPARE_FOR_SUBMISSION",
        attached: str | None = "OLD",
        sticky: bool = True,
        revert_on_read: int | None = None,
        version_exists: bool = True,
        release_type: str | None = None,
        other_versions: list[tuple[str, str]] | None = None,
        created_records: int = 1,
        bundle: str | None = BUNDLE,
        record_id: str | None = None,
        version_text: dict | None = None,
        info_text: dict | None = None,
        info_records: list[tuple[str, str, dict]] | None = None,
        locales: tuple[str, ...] = ("en-US",),
        screenshots: dict[str, list[str]] | None = None,
        screenshot_states: dict[str, list[str | None]] | None = None,
        upload_states: list[str] | None = None,
        upload_error: int | None = None,
        complete_after: int | None = None,
        unlock_state: str = "APPROVED",
        unlock_versions: list[dict] | None = None,
        iaps: list[dict] | None = None,
        iap_versions: dict[str, list[dict]] | None = None,
        subscriptions: list[dict] | None = None,
        sub_versions: dict[str, list[dict]] | None = None,
        drafts: tuple[str, ...] = ("SUB1",),
        items: list[dict] | None = None,
        draft_items: dict[str, list[dict]] | None = None,
        refuse_items: set[str] | None = None,
        build: dict | None = None,
        included: list[dict] | None = None,
        build_numbers: tuple[str, ...] = ("1", "2", "3"),
        library: list[dict] | None = None,
        placements: list[dict] | None = None,
    ) -> None:
        self.state = state
        self.attached = attached
        # attach-build changes the selection only when sticky.
        self.sticky = sticky
        # The selection reads back as OLD from this `versions view` on.
        self.revert_on_read = revert_on_read
        self.version_exists = version_exists
        self.release_type = release_type
        # The app's other iOS versions as (versionString, appStoreState).
        self.other_versions = [("1.0", "READY_FOR_SALE")] if other_versions is None else list(other_versions)
        # Records `versions create` leaves for VERSION: 1, or 0 / 2 when reading it back goes wrong.
        self.created_records = created_records
        self.bundle = bundle
        self.record_id = record_id
        self.version_text = dict(LIVE_TEXT if version_text is None else version_text)
        self.info_text = dict(LIVE_INFO if info_text is None else info_text)
        self.info_records = info_records
        self.locales = locales
        # Screenshot sets: display type -> its screenshots, in order.
        self.sets: dict[str, list[dict]] = {}
        for kind, checksums in (screenshots or {}).items():
            states = (screenshot_states or {}).get(kind, ["COMPLETE"] * len(checksums))
            self.sets[kind] = [self.shot(f"{kind}-{i}", f"{kind}-{i}.png", checksum, 1000 + i, shot_state)
                               for i, (checksum, shot_state) in enumerate(zip(checksums, states))]
        # assetDeliveryState of each image an upload adds (the last one repeats).
        self.upload_states = list(upload_states or ["COMPLETE"])
        # asc's exit code when an upload fails (after it changed the set).
        self.upload_error = upload_error
        # Images still processing turn COMPLETE on this listing since the last upload.
        self.complete_after = complete_after
        self.lists_since_upload = 0
        self.uploads: list[tuple[str, list[str]]] = []
        self.iaps = iaps if iaps is not None else [
            {"id": "IAP1", "attributes": {"name": "Unlock the Deep", "productId": UNLOCK, "state": unlock_state}}]
        self.iap_versions = iap_versions if iap_versions is not None else {
            "IAP1": unlock_versions if unlock_versions is not None else [
                {"id": "IV1", "attributes": {"version": 1, "state": "PREPARE_FOR_SUBMISSION"}}]}
        self.subscriptions = list(subscriptions or [])
        self.sub_versions = dict(sub_versions or {})
        self.drafts = list(drafts)
        self.items: dict[str, list[dict]] = {draft: [] for draft in self.drafts}
        if items is not None:
            self.items["SUB1"] = list(items)
        self.items.update({draft: list(held) for draft, held in (draft_items or {}).items()})
        self.refuse_items = set(refuse_items or ())
        self.submitted: list[str] = []
        self.created_submissions = 0
        self.build = build_row("B9") if build is None else build
        self.included = [pre_row()] if included is None else included
        self.build_numbers = list(build_numbers)
        self.library = list(library or [])
        self.placements = list(placements or [])
        self.read_only = False
        self.opened: list[bool] = []
        self.build_reads = 0
        self.calls: list[tuple[str, ...]] = []

    def open(self, *, read_only: bool = False) -> "FakeAsc":
        """Stands in for asc_release.asc_from_environment()."""
        self.read_only = read_only
        self.opened.append(read_only)
        return self

    def info_state(self) -> str:
        return "PREPARE_FOR_SUBMISSION" if self.state in asc_release.EDITABLE_VERSION_STATES else self.state

    def app_info_records(self) -> list[tuple[str, str, dict]]:
        if self.info_records is not None:
            return self.info_records
        return [("LIVE", "READY_FOR_SALE", self.info_text), ("INFO", self.info_state(), self.info_text)]

    @staticmethod
    def shot(shot_id: str, name: str, checksum: str, size: int, state: str | None) -> dict:
        attributes: dict = {"fileName": name, "fileSize": size, "sourceFileChecksum": checksum}
        if state is not None:
            errors = [{"code": "IMAGE_INCORRECT_DIMENSIONS", "description": "bad image"}] if state == "FAILED" else []
            attributes["assetDeliveryState"] = {"state": state, "errors": errors}
        return {"type": "appScreenshots", "id": shot_id, "attributes": attributes}

    def versions(self) -> list[dict]:
        rows = [{"type": "appStoreVersions", "id": f"V0-{i}",
                 "attributes": {"versionString": number, "appStoreState": state, "platform": "IOS"}}
                for i, (number, state) in enumerate(self.other_versions)]
        if self.version_exists:
            rows.append({"type": "appStoreVersions", "id": "V1",
                         "attributes": {"versionString": VERSION, "appStoreState": self.state,
                                        "releaseType": self.release_type, "platform": "IOS"}})
        return rows

    def writes(self) -> list[tuple[str, ...]]:
        """Every write asc was asked for, including ones refused in read-only mode."""
        return [call for call in self.calls if is_write(call)]

    def run(self, *args: str, **_: object):  # noqa: C901 - one branch per asc command
        self.calls.append(args)
        if self.read_only and is_write(args):
            raise asc_cli.AscError(args, 6, "refused: asc is in read-only mode (ASC_READ_ONLY)")
        if args[:2] == ("apps", "view"):
            attributes = {"bundleId": self.bundle} if self.bundle else {}
            return {"data": {"type": "apps", "id": self.record_id or flag(args, "--id"), "attributes": attributes}}
        if args[:3] == ("apps", "info", "list"):
            return {"data": [{"type": "appInfos", "id": info_id, "attributes": {"appStoreState": state}}
                             for info_id, state, _ in self.app_info_records()]}
        if args[:2] == ("versions", "list"):
            return {"data": self.versions()}
        if args[:2] == ("versions", "view"):
            self.build_reads += 1
            build = self.attached
            if self.revert_on_read is not None and self.build_reads >= self.revert_on_read:
                build = "OLD"
            relationships = {"build": {"data": {"type": "builds", "id": build} if build else None}}
            return {"data": {"type": "appStoreVersions", "id": flag(args, "--version-id"), "relationships": relationships}}
        if args[:2] == ("versions", "attach-build"):
            if self.sticky:
                self.attached = flag(args, "--build-id")
            return {"data": {}}
        if args[:2] == ("versions", "update"):
            self.release_type = flag(args, "--release-type")
            return {"data": {}}
        if args[:2] == ("versions", "create"):
            if self.created_records >= 1:
                self.version_exists = True
                self.state = "PREPARE_FOR_SUBMISSION"
            if self.created_records == 2:
                self.other_versions.append((VERSION, "PREPARE_FOR_SUBMISSION"))
            return {"data": {"type": "appStoreVersions", "id": "V1"}}
        if args[:2] == ("builds", "list"):
            if "--build-number" in args:
                return {"data": [self.build], "included": self.included}
            return {"data": [{"type": "builds", "id": f"B-{n}", "attributes": {"version": n}} for n in self.build_numbers]}
        if args[:3] == ("localizations", "placements", "list"):
            wanted = flag(args, "--placement-type")
            return {"data": [p for p in self.placements if p["attributes"]["placementType"] == wanted]}
        if args[:3] in {("localizations", "placements", "create"), ("localizations", "placements", "swap")}:
            placement_type = flag(args, "--placement-type")
            self.placements = [p for p in self.placements if p["attributes"]["placementType"] != placement_type]
            self.placements.append({"id": "PL-new", "attributes": {"placementType": placement_type},
                                    "relationships": {"image": {"data": {"id": flag(args, "--image-id")}}}})
            return {"data": {}}
        if args[:2] == ("localizations", "list"):
            locale = flag(args, "--locale") if "--locale" in args else None
            if "--type" in args and flag(args, "--type") == "app-info":
                info_id = flag(args, "--app-info")
                text = next(text for record, _, text in self.app_info_records() if record == info_id)
                found = [{"type": "appInfoLocalizations", "id": f"ILOC-{info_id}-{loc}", "attributes": {"locale": loc, **text}}
                         for loc in self.locales]
            else:
                if flag(args, "--version") != "V1":
                    raise AssertionError(f"localizations of an unknown version: {args}")
                found = [{"type": "appStoreVersionLocalizations", "id": f"LOC-{loc}",
                          "attributes": {"locale": loc, **self.version_text}} for loc in self.locales]
            return {"data": [row for row in found if locale is None or row["attributes"]["locale"] == locale]}
        if args[:2] == ("localizations", "update"):
            values = {name: flag(args, option) for name, option in asc_release.FIELD_FLAGS.items() if option in args}
            app_info = "--type" in args and flag(args, "--type") == "app-info"
            (self.info_text if app_info else self.version_text).update(values)
            return {"data": {"id": flag(args, "--id")}}
        if args[:2] == ("screenshots", "list"):
            self.lists_since_upload += 1
            if self.complete_after is not None and self.lists_since_upload >= self.complete_after:
                for shots in self.sets.values():
                    for shot in shots:
                        delivery = shot["attributes"].get("assetDeliveryState")
                        if delivery and delivery["state"] != "FAILED":
                            delivery["state"] = "COMPLETE"
            return json.loads(json.dumps({
                "versionLocalizationId": flag(args, "--version-localization"),
                "sets": [{"set": {"type": "appScreenshotSets", "id": f"SET-{kind}",
                                  "attributes": {"screenshotDisplayType": kind}}, "screenshots": shots}
                         for kind, shots in self.sets.items()],
            }))
        if args[:2] == ("screenshots", "upload"):
            if "--replace" not in args or "--confirm" not in args:
                raise AssertionError("a screenshot upload must replace the whole set")
            kind = DISPLAY_TYPES[flag(args, "--device-type")]
            files = sorted(p for p in Path(flag(args, "--path")).iterdir() if p.is_file())
            self.uploads.append((kind, [p.name for p in files]))
            states = self.upload_states
            self.sets[kind] = [
                self.shot(f"{kind}-new{len(self.uploads)}-{i}", p.name, hashlib.md5(p.read_bytes()).hexdigest(),
                          p.stat().st_size, states[min(i, len(states) - 1)])
                for i, p in enumerate(files)
            ]
            self.lists_since_upload = 0
            if self.upload_error is not None:
                raise asc_cli.AscError(args, self.upload_error, "screenshot delivery failed")
            return {"displayType": kind, "results": [{"fileName": p.name} for p in files]}
        if args[:2] == ("asset-library", "view"):
            return {"data": {"type": "appAssetLibraries", "id": "LIB1"}}
        if args[:3] == ("asset-library", "images", "list"):
            return {"data": self.library}
        if args[:3] == ("asset-library", "images", "upload"):
            path = Path(flag(args, "--file"))
            image_id = f"IMG{len(self.library) + 1}"
            self.library.append({"id": image_id, "attributes": {"fileName": path.name, "fileSize": path.stat().st_size,
                                                                "state": "PREPARE_FOR_SUBMISSION", "createdDate": "z"}})
            return {"imageId": image_id, "ready": True, "state": "PREPARE_FOR_SUBMISSION"}
        if args[:2] == ("review", "submissions-list"):
            if flag(args, "--state") != "READY_FOR_REVIEW":
                raise AssertionError(f"only drafts are listed: {args}")
            return {"data": [{"type": "reviewSubmissions", "id": draft, "attributes": {"state": "READY_FOR_REVIEW"}}
                             for draft in self.drafts]}
        if args[:2] == ("review", "submissions-create"):
            self.created_submissions += 1
            new = "NEW" if self.created_submissions == 1 else f"NEW{self.created_submissions}"
            self.drafts.append(new)
            self.items[new] = []
            return {"data": {"type": "reviewSubmissions", "id": new}}
        if args[:2] == ("review", "items-list"):
            return {"data": list(self.items.get(flag(args, "--submission"), []))}
        if args[:2] == ("review", "items-add"):
            item_type, item_id = flag(args, "--item-type"), flag(args, "--item-id")
            if flag(args, "--submission") in self.submitted:
                raise asc_cli.AscError(args, 5, "STATE_ERROR: the review submission is no longer editable")
            if item_id in self.refuse_items:
                raise asc_cli.AscError(args, 5, "conflict")
            relation = ITEM_TYPES[item_type]
            held = self.items.setdefault(flag(args, "--submission"), [])
            if any(asc_release.related_id(item, relation) == item_id for item in held):
                if flag(args, "--if-exists") != "skip":
                    raise asc_cli.AscError(args, 5, "already on the submission")
                return {"data": {}}
            held.append(review_item(f"ITEM-{item_id}", relation, item_id))
            return {"data": {}}
        if args[:2] == ("review", "submissions-submit"):
            if "--confirm" not in args:
                raise AssertionError("submitting needs --confirm")
            submission = flag(args, "--id")
            if submission in self.submitted:
                raise asc_cli.AscError(args, 5, "STATE_ERROR: the review submission was already submitted")
            self.submitted.append(submission)
            if submission in self.drafts:
                self.drafts.remove(submission)
            return {"data": {}}
        if args[:2] == ("subscriptions", "list"):
            return {"data": self.subscriptions}
        if args[:3] == ("subscriptions", "versions", "list"):
            return {"data": self.sub_versions.get(flag(args, "--subscription-id"), [])}
        if args[:2] == ("iap", "list"):
            return {"data": self.iaps}
        if args[:3] == ("iap", "versions", "list"):
            return {"data": self.iap_versions.get(flag(args, "--iap-id"), [])}
        raise AssertionError(f"unexpected asc call {args}")


class CmdWaitBuildTests(unittest.TestCase):
    def test_deadline_counts_from_upload_start_and_app_lookup_is_retried(self) -> None:
        lookups = []

        class Lookup:
            def run(self, *args: str, **_: object):
                lookups.append(args)
                if len(lookups) == 1:
                    raise asc_error(63)
                return {"data": {"id": APP, "attributes": {"bundleId": ios_release.BUNDLE_ID}}}

        captured = {}

        def fake_wait(client, **kwargs):
            captured.update(kwargs)
            return {"id": "B9"}

        args = argparse.Namespace(version=VERSION, build=3, started_at=STARTED, wait_minutes=120, poll_seconds=30)
        with tempfile.NamedTemporaryFile("r", suffix=".out") as out, \
                mock.patch.object(ios_release, "asc_client", return_value=(asc_release, Lookup())), \
                mock.patch.object(ios_release, "wait_for_build", side_effect=fake_wait), \
                mock.patch.object(ios_release.time, "sleep"), \
                mock.patch.object(ios_release.time, "time", return_value=STARTED + 30), \
                mock.patch.dict(os.environ, {"GITHUB_OUTPUT": out.name}), redirect_stdout(io.StringIO()):
            ios_release.cmd_wait_build(args)
            written = Path(out.name).read_text()
        self.assertEqual(lookups, [("apps", "view", "--id", APP)] * 2)
        self.assertEqual(captured["app_id"], APP)
        self.assertEqual(captured["deadline"], STARTED + 120 * 60)
        self.assertEqual(captured["uploaded_after"], STARTED)
        self.assertEqual(captured["build_number"], "3")
        self.assertIs(captured["is_transient"], ios_release.is_transient_error)
        self.assertIn("build_id=B9", written)

    def test_runs_alone_as_the_build_job_checks_it_out(self) -> None:
        # The build job's sparse checkout holds ios_release.py (and the log
        # redactor) without asc_cli.py, and runs its export compliance check.
        build = WorkflowWiringTests.WORKFLOW.split("\n  build:\n", 1)[1].split("\n  wait-for-build:\n", 1)[0]
        self.assertIn("            /scripts/store/ios_release.py\n", build)
        self.assertNotIn("asc_cli.py", build)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "ios_release.py"
            shutil.copy(HERE / "ios_release.py", copy)
            info = Path(tmp) / "Info.plist"
            info.write_bytes(plistlib.dumps({"CFBundleIdentifier": ios_release.BUNDLE_ID,
                                             "ITSAppUsesNonExemptEncryption": False}))
            for args in (["export-compliance", "--help"], ["export-compliance", "--info-plist", str(info)]):
                done = subprocess.run([sys.executable, "-I", str(copy), *args], capture_output=True, text=True,
                                      timeout=60, check=False, cwd=tmp)
                with self.subTest(args=args):
                    self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("ITSAppUsesNonExemptEncryption = NO", done.stdout)

    def test_errors_that_are_not_asc_errors_are_not_swallowed(self) -> None:
        with mock.patch.object(ios_release, "asc_client", side_effect=KeyError("unexpected")), \
                mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()), \
                self.assertRaises(KeyError):
            ios_release.main(["wait-build", "--version", VERSION, "--build", "3", "--started-at", str(STARTED),
                              "--wait-minutes", "120", "--poll-seconds", "30"])

    def test_asc_errors_end_with_an_error_line_not_a_traceback(self) -> None:
        err = io.StringIO()
        with mock.patch.object(ios_release, "asc_client", side_effect=asc_cli.AscError(("apps", "view"), 3, "unauthorized")), \
                mock.patch.dict(os.environ, {}, clear=True), redirect_stderr(err), redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit) as caught:
            ios_release.main(["wait-build", "--version", VERSION, "--build", "3", "--started-at", str(STARTED),
                              "--wait-minutes", "120", "--poll-seconds", "30"])
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("error: asc apps view failed (exit 3)", err.getvalue())

    def test_another_app_record_stops_the_wait(self) -> None:
        for record in ({"id": APP, "attributes": {"bundleId": "com.example.other"}},
                       {"id": "999", "attributes": {"bundleId": ios_release.BUNDLE_ID}}):
            class Other:
                def run(self, *args: str, _record: dict = record, **_: object):
                    return {"data": _record}

            args = argparse.Namespace(version=VERSION, build=3, started_at=STARTED, wait_minutes=120, poll_seconds=30)
            with self.subTest(record=record), \
                    mock.patch.object(ios_release, "asc_client", return_value=(asc_release, Other())), \
                    mock.patch.object(ios_release.time, "time", return_value=STARTED), \
                    redirect_stdout(io.StringIO()), self.assertRaises(ReleaseError):
                ios_release.cmd_wait_build(args)

    def test_app_lookup_gives_up_at_the_deadline(self) -> None:
        def boom():
            raise asc_error(63)

        clock = FakeClock(STARTED)
        with redirect_stdout(io.StringIO()), self.assertRaises(asc_cli.AscError):
            ios_release.call_with_retries(boom, deadline=STARTED + 90, poll_seconds=30, now=clock.now, sleep=clock.sleep)
        self.assertEqual(clock.sleeps, [30, 30, 30])

    def test_build_numbering_and_the_build_wait_run_asc_read_only(self) -> None:
        env = {"APP_STORE_CONNECT_API_KEY_ID": "K", "APP_STORE_CONNECT_ISSUER_ID": "I", "APP_STORE_CONNECT_API_KEY_P8": "P"}
        with mock.patch.dict(os.environ, env, clear=True):
            module, client = ios_release.asc_client()
        self.assertIs(module, asc_release)
        self.assertTrue(client.read_only)


class CmdBuildNumberTests(unittest.TestCase):
    def test_uses_the_highest_uploaded_build_plus_one(self) -> None:
        fake = FakeAsc(build_numbers=("1", "2", "5"))
        with tempfile.NamedTemporaryFile("r", suffix=".out") as out, \
                mock.patch.object(ios_release, "asc_client", return_value=(asc_release, fake)), \
                mock.patch.object(ios_release, "project_build_number", return_value=2), \
                mock.patch.dict(os.environ, {"GITHUB_OUTPUT": out.name}), redirect_stdout(io.StringIO()):
            ios_release.cmd_build_number(argparse.Namespace())
            self.assertIn("build_number=6", Path(out.name).read_text())
        self.assertEqual(fake.calls[0], ("apps", "view", "--id", APP))  # the pinned app first
        listing = fake.calls[1]
        # Every build counts, whatever its processing state, across every page.
        self.assertEqual(listing[:2], ("builds", "list"))
        self.assertEqual((flag(listing, "--app"), flag(listing, "--processing-state")), (APP, "all"))
        self.assertIn("--paginate", listing)
        self.assertEqual(fake.writes(), [])


class FindAppTests(unittest.TestCase):
    def test_returns_abysm_only(self) -> None:
        fake = FakeAsc()
        self.assertEqual(quiet(asc_release.find_app, fake, BUNDLE), APP)
        self.assertEqual(fake.calls, [("apps", "view", "--id", APP)])

    def test_wrong_or_unverifiable_app_fails(self) -> None:
        cases = {
            "other bundle id": FakeAsc(bundle="com.example.other"),
            "prefix only": FakeAsc(bundle=BUNDLE + ".beta"),
            "no bundle id reported": FakeAsc(bundle=None),
            "another record": FakeAsc(record_id="999"),
        }
        for label, fake in cases.items():
            with self.subTest(label), self.assertRaises(SystemExit):
                quiet(asc_release.find_app, fake, BUNDLE)
        # The pinned record never stands in for another bundle id.
        with self.assertRaises(SystemExit):
            quiet(asc_release.find_app, FakeAsc(), "com.example.other")

    def test_asc_failures_stop_with_a_readable_error(self) -> None:
        class Broken:
            def run(self, *args: str, **_: object):
                raise asc_cli.AscError(args, 3, "unauthorized")

        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit):
            asc_release.find_app(Broken(), BUNDLE)
        self.assertIn("exit 3", err.getvalue())


class BuildSelectionTests(unittest.TestCase):
    def test_selects_and_reads_back_this_runs_build(self) -> None:
        fake = FakeAsc()
        quiet(asc_release.select_build, fake, "V1", "B9", VERSION, "3")
        self.assertEqual(fake.attached, "B9")
        self.assertEqual([c[:2] for c in fake.calls],
                         [("builds", "list"), ("versions", "view"), ("versions", "attach-build"), ("versions", "view")])
        self.assertEqual(fake.writes(), [("versions", "attach-build", "--version-id", "V1", "--build-id", "B9")])
        check = fake.calls[0]
        self.assertEqual((flag(check, "--app"), flag(check, "--build-number"), flag(check, "--version"),
                          flag(check, "--platform"), flag(check, "--processing-state"), flag(check, "--include")),
                         (APP, "3", VERSION, "IOS", "all", "preReleaseVersion"))
        self.assertEqual(flag(fake.calls[-1], "--include"), "build")

    def test_a_build_already_selected_is_only_read_back(self) -> None:
        fake = FakeAsc(attached="B9")
        quiet(asc_release.select_build, fake, "V1", "B9", VERSION, "3")
        self.assertEqual(fake.writes(), [])

    def test_selection_that_does_not_stick_fails(self) -> None:
        fake = FakeAsc(sticky=False)
        with self.assertRaises(SystemExit):
            quiet(asc_release.select_build, fake, "V1", "B9", VERSION, "3")

    def test_unprocessed_expired_or_wrong_build_is_refused(self) -> None:
        cases = {
            "processing": (build_row("B9", state="PROCESSING"), [pre_row()]),
            "expired": (build_row("B9", expired=True), [pre_row()]),
            "number": (build_row("B9", number="4"), [pre_row()]),
            "version": (build_row("B9"), [pre_row(version="1.0")]),
            "platform": (build_row("B9"), [pre_row(platform="TV_OS")]),
            "not listed": (build_row("B8"), [pre_row()]),
        }
        for label, (build, included) in cases.items():
            fake = FakeAsc(build=build, included=included)
            with self.subTest(label), self.assertRaises(SystemExit):
                quiet(asc_release.select_build, fake, "V1", "B9", VERSION, "3")
            self.assertEqual(fake.writes(), [], label)

    def test_release_type(self) -> None:
        for public, expected in ((True, "AFTER_APPROVAL"), (False, "MANUAL")):
            fake = FakeAsc()
            quiet(asc_release.set_release_type, fake, "V1", public_release=public)
            self.assertEqual(fake.writes(), [("versions", "update", "--version-id", "V1", "--release-type", expected)])
            same = FakeAsc()
            quiet(asc_release.set_release_type, same, "V1", public_release=public, current=expected)
            self.assertEqual(same.writes(), [])


def png(path: Path, width: int, height: int, *, color_type: int = 2) -> Path:
    """A PNG header of the given size; RGB (colour type 2) unless asked, since asc refuses alpha."""
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR"
                     + width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, color_type, 0, 0, 0]))
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


class ScreenshotUploadTests(unittest.TestCase):
    def plan(self, tmp: str, count: int) -> list:
        files = [png(Path(tmp) / f"{i:02}.png", 2796, 1290) for i in range(count)]
        for i, path in enumerate(files):  # distinct contents, so each file has its own checksum
            path.write_bytes(path.read_bytes() + bytes([i]))
        return [(IPHONE, files)]

    def upload(self, fake: FakeAsc, plan: list, **kwargs) -> list[str]:
        kwargs.setdefault("wait", lambda asc, loc, uploaded: None)
        return quiet(asc_release.upload_screenshots, fake, version_id="V1", locale="en-US", plan=plan, **kwargs)

    def test_screenshots_that_store_alpha_are_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rgb = png(Path(tmp) / "01-rgb.png", 2796, 1290)
            rgba = png(Path(tmp) / "02-rgba.png", 2796, 1290, color_type=6)
            trns = Path(tmp) / "03-trns.png"
            trns.write_bytes(png_header(2, trns=True))
            self.assertIsNone(asc_release.screenshot_alpha_problem([(IPHONE, [rgb])]))
            problem = asc_release.screenshot_alpha_problem([(IPHONE, [rgb, rgba]), (IPAD, [trns])])
            self.assertIn(f"{IPHONE}: 02-rgba.png; {IPAD}: 03-trns.png", problem)
            self.assertIn("Re-export them as RGB PNGs", problem)

    def test_screenshot_sizes_are_exactly_what_asc_accepts(self) -> None:
        # `asc screenshots sizes --display-type <TYPE>` (asc 5.15.0).
        asc_sizes = {
            IPHONE: {(1260, 2736), (1290, 2796), (1320, 2868), (2736, 1260), (2796, 1290), (2868, 1320)},
            IPAD: {(2048, 2732), (2064, 2752), (2732, 2048), (2752, 2064)},
        }
        self.assertEqual({display: set(accepted) for display, _, accepted in asc_release.SCREENSHOT_SETS}, asc_sizes)
        self.assertNotIn((1284, 2778), asc_sizes[IPHONE])  # the 6.5" size, which the 6.7" set refuses

    def test_every_set_has_an_asc_device_type(self) -> None:
        self.assertEqual({display for display, *_ in asc_release.SCREENSHOT_SETS}, set(asc_release.DEVICE_TYPES))
        self.assertEqual(asc_release.DEVICE_TYPES, {IPHONE: "IPHONE_67", IPAD: "IPAD_PRO_3GEN_129"})

    def test_replaces_a_differing_set_with_exactly_the_repo_images_in_order(self) -> None:
        fake = FakeAsc(screenshots={IPHONE: [f"old{i}" for i in range(10)]})
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.plan(tmp, 5)
            (Path(tmp) / "notes.txt").write_text("not a screenshot")  # never uploaded
            self.assertEqual(self.upload(fake, plan), [IPHONE])
            wanted = [asc_release.md5_hex(p) for p in plan[0][1]]
        self.assertEqual(len(fake.writes()), 1)
        upload = fake.writes()[0]
        self.assertEqual(upload[:2], ("screenshots", "upload"))
        self.assertEqual((flag(upload, "--version-localization"), flag(upload, "--device-type")), ("LOC-en-US", "IPHONE_67"))
        # --replace swaps the whole set (asc deletes the old images first), so a full set is never a problem.
        self.assertIn("--replace", upload)
        self.assertIn("--confirm", upload)
        self.assertEqual(fake.uploads, [(IPHONE, [f"{i:02}.png" for i in range(5)])])
        self.assertEqual([s["attributes"]["sourceFileChecksum"] for s in fake.sets[IPHONE]], wanted)

    def test_a_set_that_already_matches_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.plan(tmp, 3)
            same = [asc_release.md5_hex(p) for p in plan[0][1]]
            for editable in (True, False):
                fake = FakeAsc(screenshots={IPHONE: same})
                differing = self.upload(fake, plan, editable=editable, state="READY_FOR_REVIEW")
                self.assertEqual((differing, fake.writes()), ([], []), editable)
            # Same images in another order still differ.
            fake = FakeAsc(screenshots={IPHONE: list(reversed(same))})
            self.assertEqual(self.upload(fake, plan), [IPHONE])

    def test_locked_or_read_only_runs_never_change_screenshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.plan(tmp, 2)
            locked = FakeAsc(screenshots={IPHONE: ["old", "old"]})
            err = io.StringIO()
            with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), redirect_stderr(err):
                asc_release.upload_screenshots(locked, version_id="V1", locale="en-US", plan=plan,
                                               wait=lambda *_: None, editable=False, state="READY_FOR_REVIEW")
            self.assertIn("READY_FOR_REVIEW", err.getvalue())
            self.assertEqual(locked.writes(), [])
            for preview in (FakeAsc(screenshots={IPHONE: ["old", "old"]}), FakeAsc()):  # differing or missing set
                self.assertEqual(self.upload(preview, plan, write=False), [IPHONE])
                self.assertEqual(preview.writes(), [])

    def test_waits_for_processing_and_fails_on_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.plan(tmp, 1)
            same = [asc_release.md5_hex(p) for p in plan[0][1]]

            def wait_for(fake: FakeAsc, clock: FakeClock, timeout: float = 60) -> None:
                asc_release.wait_for_screenshots(fake, "LOC-en-US", plan, timeout=timeout, poll_seconds=5,
                                                 now=clock.now, sleep=clock.sleep)

            clock = FakeClock(0)
            processing = FakeAsc(screenshots={IPHONE: same}, screenshot_states={IPHONE: ["UPLOAD_COMPLETE"]},
                                 complete_after=2)
            quiet(wait_for, processing, clock)
            self.assertEqual(clock.sleeps, [5])
            failed = FakeAsc(screenshots={IPHONE: same}, screenshot_states={IPHONE: ["FAILED"]})
            err = io.StringIO()
            with self.assertRaises(SystemExit), redirect_stderr(err):
                wait_for(failed, clock)
            self.assertIn(f"App Store Connect rejected screenshot {IPHONE}-0.png: bad image", err.getvalue())
            stuck = FakeAsc(screenshots={IPHONE: same}, screenshot_states={IPHONE: ["UPLOAD_COMPLETE"]})
            clock = FakeClock(0)
            with self.assertRaises(SystemExit):
                quiet(wait_for, stuck, clock, 20)
            self.assertEqual(clock.time, 20)
            # A set that does not hold the repo's images after the upload fails at once.
            for other in (FakeAsc(screenshots={IPHONE: ["other"]}), FakeAsc()):
                clock = FakeClock(0)
                with self.assertRaises(SystemExit):
                    quiet(wait_for, other, clock)
                self.assertEqual(clock.sleeps, [])

    def test_the_repo_images_count_as_uploaded_only_once_apple_has_processed_them(self) -> None:
        # The commit stores sourceFileChecksum before Apple processes the image, so a set
        # left by a failed or timed-out wait already holds the repo's checksums.
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.plan(tmp, 3)
            same = [asc_release.md5_hex(p) for p in plan[0][1]]
            for unfinished in ("FAILED", "UPLOAD_COMPLETE", "AWAITING_UPLOAD", None):
                states = {IPHONE: ["COMPLETE", unfinished, "COMPLETE"]}
                with self.subTest(state=unfinished):
                    # Editable: the whole set is uploaded again, and the new images are waited for.
                    fake = FakeAsc(screenshots={IPHONE: same}, screenshot_states=states)
                    waited: list = []
                    differing = self.upload(fake, plan, wait=lambda asc, loc, uploaded: waited.extend(uploaded))
                    self.assertEqual(differing, [IPHONE])
                    self.assertEqual([kind for kind, _ in waited], [IPHONE])
                    self.assertEqual(fake.uploads, [(IPHONE, ["00.png", "01.png", "02.png"])])
                    # Locked: fails without a write and names the unfinished image.
                    locked = FakeAsc(screenshots={IPHONE: same}, screenshot_states=states)
                    err = io.StringIO()
                    with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), redirect_stderr(err):
                        asc_release.upload_screenshots(locked, version_id="V1", locale="en-US", plan=plan,
                                                       wait=lambda *_: None, editable=False, state="IN_REVIEW")
                    self.assertIn(f"{IPHONE}-1.png: {unfinished or 'no processing state'}", err.getvalue())
                    self.assertIn("screenshots cannot change while the version is IN_REVIEW", err.getvalue())
                    self.assertEqual(locked.writes(), [])
                    # Preflight: reported, nothing sent.
                    preview = FakeAsc(screenshots={IPHONE: same}, screenshot_states=states)
                    out = io.StringIO()
                    with redirect_stdout(out), redirect_stderr(io.StringIO()):
                        differing = asc_release.upload_screenshots(preview, version_id="V1", locale="en-US", plan=plan,
                                                                   wait=lambda *_: None, write=False)
                    self.assertEqual((differing, preview.writes()), ([IPHONE], []))
                    self.assertIn("would replace", out.getvalue())

    def test_a_rerun_repairs_a_set_left_by_a_failed_or_timed_out_wait(self) -> None:
        # Apple rejects an image (asc fails the upload), or is still processing it at
        # the deadline; then "Re-run failed jobs" must upload the set again, not take it as done.
        for first_attempt in ("FAILED", "UPLOAD_COMPLETE"):
            with self.subTest(first_attempt=first_attempt), tempfile.TemporaryDirectory() as tmp:
                plan = self.plan(tmp, 2)
                clock = FakeClock(0)
                fake = FakeAsc(screenshots={IPHONE: ["old", "old"]}, upload_states=[first_attempt],
                               upload_error=1 if first_attempt == "FAILED" else None)

                def run() -> list[str]:
                    return self.upload(fake, plan, wait=lambda asc, loc, uploaded: asc_release.wait_for_screenshots(
                        asc, loc, uploaded, timeout=20, poll_seconds=5, now=clock.now, sleep=clock.sleep))

                with self.assertRaises(SystemExit):
                    run()
                first = [s["id"] for s in fake.sets[IPHONE]]
                self.assertEqual([s["attributes"]["sourceFileChecksum"] for s in fake.sets[IPHONE]],
                                 [asc_release.md5_hex(p) for p in plan[0][1]])
                fake.upload_states, fake.upload_error = ["COMPLETE"], None  # this time Apple processes the images
                self.assertEqual(run(), [IPHONE])
                self.assertTrue(set(first).isdisjoint(s["id"] for s in fake.sets[IPHONE]))
                self.assertEqual([s["attributes"]["assetDeliveryState"]["state"] for s in fake.sets[IPHONE]],
                                 ["COMPLETE", "COMPLETE"])
                # Once the set is done, a further re-run sends nothing.
                writes = len(fake.writes())
                self.assertEqual(run(), [])
                self.assertEqual(len(fake.writes()), writes)


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

    def updates(self, fake: FakeAsc) -> list[tuple[str, ...]]:
        return [c for c in fake.calls if c[:2] == ("localizations", "update")]

    def sync(self, fake: FakeAsc, files: dict, **kwargs) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            return quiet(asc_release.upload_listing, fake, app_id=APP, version_id="V1", locale="en-US",
                         metadata_dir=metadata_tree(tmp, files), **kwargs)

    def test_only_changed_fields_are_sent_and_whats_new_has_its_own_switch(self) -> None:
        files = {"description.txt": "New desc\n", "keywords.txt": "same", "whats_new.txt": "Fixes"}
        fake = FakeAsc(version_text={"description": "Old desc", "keywords": "same"})
        self.sync(fake, files)
        self.assertEqual(self.updates(fake), [("localizations", "update", "--id", "LOC-en-US", "--description", "New desc")])
        fake = FakeAsc(version_text={"description": "New desc", "keywords": "same"})
        self.sync(fake, files, include_listing=False, include_whats_new=True)
        self.assertEqual(self.updates(fake), [("localizations", "update", "--id", "LOC-en-US", "--whats-new", "Fixes")])
        fake = FakeAsc(version_text={"description": "New desc", "keywords": "same", "whatsNew": "Fixes"})
        self.sync(fake, files, include_listing=True, include_whats_new=True)
        self.assertEqual(self.updates(fake), [])

    def test_every_changed_field_goes_in_one_update_per_localization(self) -> None:
        files = {"description.txt": "D2", "keywords.txt": "k2", "promotional_text.txt": "P", "marketing_url.txt":
                 "https://abysm.apoorvdarshan.com", "support_url.txt": "https://abysm.apoorvdarshan.com/support",
                 "whats_new.txt": "W", "name.txt": "ABYSM", "subtitle.txt": "S", "privacy_url.txt":
                 "https://abysm.apoorvdarshan.com/privacy", "privacy_choices_url.txt": "https://abysm.apoorvdarshan.com/choices"}
        fake = FakeAsc(version_text={}, info_text={})
        self.sync(fake, files, include_whats_new=True)
        version, info = self.updates(fake)
        self.assertEqual(version, ("localizations", "update", "--id", "LOC-en-US", "--description", "D2", "--keywords", "k2",
                                   "--marketing-url", "https://abysm.apoorvdarshan.com", "--promotional-text", "P",
                                   "--support-url", "https://abysm.apoorvdarshan.com/support", "--whats-new", "W"))
        self.assertEqual(info, ("localizations", "update", "--type", "app-info", "--id", "ILOC-INFO-en-US", "--name", "ABYSM",
                                "--privacy-choices-url", "https://abysm.apoorvdarshan.com/choices",
                                "--privacy-policy-url", "https://abysm.apoorvdarshan.com/privacy", "--subtitle", "S"))
        # A second run finds everything in place and sends nothing.
        self.sync(fake, files, include_whats_new=True)
        self.assertEqual(len(self.updates(fake)), 2)

    def test_app_info_is_updated_only_while_editable(self) -> None:
        files = {"description.txt": "D", "keywords.txt": "k", "subtitle.txt": "A new subtitle"}
        fake = FakeAsc(version_text={"description": "D", "keywords": "k"}, info_text={"subtitle": "Old"})
        self.sync(fake, files)
        self.assertEqual(self.updates(fake), [("localizations", "update", "--type", "app-info", "--id", "ILOC-INFO-en-US",
                                               "--subtitle", "A new subtitle")])
        locked = FakeAsc(state="READY_FOR_SALE", version_text={"description": "D", "keywords": "k"},
                         info_text={"subtitle": "Old"})
        with self.assertRaises(SystemExit):
            self.sync(locked, files)
        self.assertEqual(locked.writes(), [])
        same = FakeAsc(state="READY_FOR_SALE", version_text={"description": "D", "keywords": "k"},
                       info_text={"subtitle": "A new subtitle"})
        self.sync(same, files)
        self.assertEqual(same.writes(), [])

    def test_missing_localization_fails(self) -> None:
        for fake in (FakeAsc(locales=("fr-FR",)), FakeAsc(locales=())):
            err = io.StringIO()
            with self.subTest(locales=fake.locales), self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), \
                    redirect_stderr(err), tempfile.TemporaryDirectory() as tmp:
                asc_release.upload_listing(fake, app_id=APP, version_id="V1", locale="en-US",
                                           metadata_dir=metadata_tree(tmp, {"description.txt": "D"}))
            self.assertIn("no en-US localization", err.getvalue())
            self.assertEqual(fake.writes(), [])

    def test_locked_text_is_compared_never_changed(self) -> None:
        # WAITING_FOR_REVIEW / IN_REVIEW: a re-run passes only when nothing would change.
        files = {"description.txt": "D", "keywords.txt": "k", "whats_new.txt": "Fixes", "subtitle.txt": "Sub"}
        locked = {"text_editable": False, "include_whats_new": True, "state": "WAITING_FOR_REVIEW"}
        same = FakeAsc(state="WAITING_FOR_REVIEW", version_text={"description": "D", "keywords": "k", "whatsNew": "Fixes"},
                       info_text={"subtitle": "Sub"})
        self.assertEqual(self.sync(same, files, **locked), [])
        self.assertEqual(same.writes(), [])
        for version_text, info_text in (({"description": "Old", "keywords": "k", "whatsNew": "Fixes"}, {"subtitle": "Sub"}),
                                        ({"description": "D", "keywords": "k", "whatsNew": "Fixes"}, {"subtitle": "Old"})):
            differs = FakeAsc(state="WAITING_FOR_REVIEW", version_text=version_text, info_text=info_text)
            with self.subTest(version=version_text, info=info_text), self.assertRaises(SystemExit):
                self.sync(differs, files, **locked)
            self.assertEqual(differs.writes(), [])

    def test_read_only_run_reports_changes_without_sending_them(self) -> None:
        files = {"description.txt": "New", "keywords.txt": "k", "subtitle.txt": "New sub"}
        fake = FakeAsc(version_text={"description": "Old", "keywords": "k"}, info_text={"subtitle": "Old"})
        self.assertEqual(self.sync(fake, files, write=False), ["en-US description", "en-US subtitle"])
        self.assertEqual(fake.writes(), [])

    def test_app_info_of_the_version_in_review_is_compared_not_the_live_one(self) -> None:
        records = [("LIVE", "READY_FOR_SALE", {"subtitle": "Live subtitle"}),
                   ("NEXT", "WAITING_FOR_REVIEW", {"subtitle": "Next subtitle"})]
        fake = FakeAsc(state="WAITING_FOR_REVIEW", version_text={"description": "D", "keywords": "k"}, info_records=records)
        self.assertEqual(asc_release.choose_app_info(fake, APP), ({"type": "appInfos", "id": "NEXT",
                                                                    "attributes": {"appStoreState": "WAITING_FOR_REVIEW"}}, False))
        files = {"description.txt": "D", "keywords.txt": "k", "subtitle.txt": "Next subtitle"}
        self.assertEqual(self.sync(fake, files, text_editable=False, state="WAITING_FOR_REVIEW"), [])
        self.assertEqual(fake.writes(), [])
        reads = [c for c in fake.calls if c[:2] == ("localizations", "list") and "app-info" in c]
        self.assertTrue(reads and all(flag(c, "--app-info") == "NEXT" for c in reads))

    def test_ready_for_review_text_and_app_info_stay_editable(self) -> None:
        self.assertIn("READY_FOR_REVIEW", asc_release.TEXT_EDITABLE_VERSION_STATES)
        self.assertIn("READY_FOR_REVIEW", asc_release.EDITABLE_APP_INFO_STATES)
        self.assertNotIn("READY_FOR_REVIEW", asc_release.EDITABLE_VERSION_STATES)  # screenshots are locked

    def test_a_leading_at_sign_reaches_asc_escaped(self) -> None:
        # asc reads a value that starts with @ as @file:/@env:; the text itself must arrive.
        fake = FakeAsc(version_text={"description": "D", "keywords": "k"})
        self.sync(fake, {"description.txt": "@apoorvcodes made this", "keywords.txt": "k"})
        self.assertEqual(flag(self.updates(fake)[0], "--description"), "@@apoorvcodes made this")


PASS = "com.apoorvdarshan.Abysm.pass"


def product_fake(unlock_state: str = "READY_TO_SUBMIT", *, drafts: tuple[str, ...] = ("SUB1",), **kwargs) -> FakeAsc:
    """A catalog subscription with two versions, a subscription and an in-app purchase
    outside the catalog, and Unlock the Deep with an approved and a new version."""
    return FakeAsc(
        drafts=drafts,
        subscriptions=[
            {"id": "S1", "attributes": {"name": "Deep Pass", "productId": PASS, "state": "DEVELOPER_REJECTED"}},
            {"id": "SX", "attributes": {"name": "Legacy", "productId": "com.apoorvdarshan.Abysm.legacy",
                                        "state": "READY_TO_SUBMIT"}},
        ],
        sub_versions={"S1": [{"id": "V1b", "attributes": {"version": 2}}, {"id": "V1a", "attributes": {"version": 1}}],
                      "SX": [{"id": "SXv", "attributes": {"version": 1}}]},
        iaps=[
            {"id": "IAP1", "attributes": {"name": "Unlock the Deep", "productId": UNLOCK, "state": unlock_state}},
            {"id": "IAP2", "attributes": {"name": "Other", "productId": "com.apoorvdarshan.Abysm.other",
                                          "state": "READY_TO_SUBMIT"}},
        ],
        iap_versions=kwargs.pop("iap_versions", {
            "IAP1": [{"id": "IV1", "attributes": {"version": 1, "state": "APPROVED"}},
                     {"id": "IV2", "attributes": {"version": 2, "state": "PREPARE_FOR_SUBMISSION"}}],
            "IAP2": [{"id": "IAP2v", "attributes": {"version": 1}}],
        }),
        **kwargs,
    )


class ProductAttachTests(unittest.TestCase):
    INTENDED = {UNLOCK, PASS}

    def attach(self, fake: FakeAsc, **kwargs) -> asc_release.ProductAttachResult:
        return quiet(asc_release.attach_catalog_products, fake, APP, **kwargs)

    def test_ready_catalog_products_join_the_draft_and_nothing_is_submitted(self) -> None:
        fake = product_fake()
        result = self.attach(fake, intended_ids=self.INTENDED)
        self.assertEqual((result.attached, result.added_items, result.submission_id), (2, True, "SUB1"))
        # The newest version of each product becomes an item of the same draft as the app.
        self.assertEqual(items_added(fake), [("subscriptionVersions", "V1b"), ("inAppPurchaseVersions", "IV2")])
        adds = [c for c in fake.calls if c[:2] == ("review", "items-add")]
        self.assertTrue(all(flag(c, "--submission") == "SUB1" and flag(c, "--if-exists") == "skip" for c in adds))
        # Nothing reaches App Review here, and no draft is created next to the existing one.
        self.assertEqual([c[:2] for c in fake.writes()], [("review", "items-add")] * 2)
        self.assertEqual(fake.submitted, [])
        # Every version of every catalog product may sit in the draft when it is submitted.
        self.assertEqual(result.allowed_versions, {"V1a", "V1b", "IV1", "IV2"})
        # Products outside the catalog are never even read.
        self.assertFalse([c for c in fake.calls if "SX" in c or "IAP2" in c])

    def test_approved_unlock_is_never_resubmitted(self) -> None:
        fake = product_fake(unlock_state="APPROVED")
        result = self.attach(fake, intended_ids={UNLOCK})
        self.assertEqual(result.attached, 0)
        self.assertEqual(fake.writes(), [])
        self.assertEqual(result.allowed_versions, {"IV1", "IV2"})

    def test_retry_skips_products_already_in_the_draft(self) -> None:
        fake = product_fake(items=[review_item("I1", "subscriptionVersion", "V1b"),
                                   review_item("I2", "inAppPurchaseVersion", "IV2")])
        result = self.attach(fake, intended_ids=self.INTENDED)
        self.assertEqual((result.attached, result.added_items), (2, False))
        self.assertEqual(fake.writes(), [])

    def test_draft_items_are_read_with_their_related_versions(self) -> None:
        fake = product_fake()
        self.attach(fake, intended_ids=self.INTENDED)
        listing = [c for c in fake.calls if c[:2] == ("review", "items-list")][0]
        self.assertEqual(set(flag(listing, "--include").split(",")),
                         {"appStoreVersion", "subscriptionVersion", "inAppPurchaseVersion", "appAssetLibraryImage"})
        self.assertIn("--paginate", listing)

    def test_failed_or_versionless_required_product_raises(self) -> None:
        fake = product_fake(refuse_items={"IV2"})
        with self.assertRaisesRegex(asc_release.ProductSubmitError, r"Unlock the Deep .*exit 5"):
            self.attach(fake, intended_ids={UNLOCK})
        fake = product_fake(iap_versions={"IAP1": []})
        with self.assertRaisesRegex(asc_release.ProductSubmitError, "no version to submit"):
            self.attach(fake, intended_ids={UNLOCK})
        self.assertEqual(fake.writes(), [])

    def test_a_draft_is_created_only_when_something_needs_one(self) -> None:
        idle = product_fake(unlock_state="APPROVED", drafts=())
        result = self.attach(idle, intended_ids={UNLOCK})
        self.assertEqual((result.attached, result.submission_id, idle.writes()), (0, "", []))
        busy = product_fake(drafts=())
        result = self.attach(busy, intended_ids={UNLOCK})
        self.assertEqual([c[:2] for c in busy.writes()], [("review", "submissions-create"), ("review", "items-add")])
        self.assertEqual(result.submission_id, "NEW")

    def test_a_draft_holding_an_app_version_is_never_used_for_products_alone(self) -> None:
        theirs = [review_item("V", "appStoreVersion", "V0-0")]
        fake = product_fake(drafts=("THEIRS",), draft_items={"THEIRS": theirs})
        result = self.attach(fake, intended_ids={UNLOCK})
        self.assertEqual(result.submission_id, "NEW")
        self.assertEqual(fake.items["THEIRS"], theirs)
        # The draft holding the version asked for is reused, and wins over an empty one.
        mine = [review_item("V", "appStoreVersion", "V1")]
        fake = product_fake(drafts=("EMPTY", "MINE"), draft_items={"MINE": mine})
        self.assertEqual(asc_release.find_draft_submission(fake, APP, "V1"), "MINE")
        self.assertEqual(asc_release.find_draft_submission(fake, APP), "EMPTY")

    def test_a_draft_holding_creative_images_is_never_used_for_products(self) -> None:
        creative = [review_item("IMG", "appAssetLibraryImage", "H")]
        fake = product_fake(drafts=("CREATIVE",), draft_items={"CREATIVE": creative})
        result = self.attach(fake, intended_ids={UNLOCK})
        self.assertEqual(result.submission_id, "NEW")
        self.assertEqual(fake.items["CREATIVE"], creative)

    def test_empty_catalog_submits_nothing(self) -> None:
        fake = product_fake()
        result = self.attach(fake, intended_ids=set())
        self.assertEqual(result.attached, 0)
        self.assertEqual(fake.calls, [])

    def test_submit_for_review_does_not_add_the_version_twice(self) -> None:
        held = FakeAsc(items=[review_item("I1", "appStoreVersion", "V1")])
        quiet(asc_release.submit_for_review, held, APP, "V1", "PREPARE_FOR_SUBMISSION", submission_id="SUB1")
        self.assertEqual(held.writes(), [("review", "submissions-submit", "--id", "SUB1", "--confirm")])
        fresh = FakeAsc()
        quiet(asc_release.submit_for_review, fresh, APP, "V1", "PREPARE_FOR_SUBMISSION", submission_id="SUB1")
        self.assertEqual(items_added(fresh), [("appStoreVersions", "V1")])
        self.assertEqual(fresh.submitted, ["SUB1"])

    def test_a_ready_for_review_version_must_be_in_the_draft_that_is_submitted(self) -> None:
        # Submitting a draft without the version would send its products to App Review alone.
        fake = FakeAsc(state="READY_FOR_REVIEW", items=[review_item("I1", "inAppPurchaseVersion", "IV1")])
        with self.assertRaises(SystemExit):
            quiet(asc_release.submit_for_review, fake, APP, "V1", "READY_FOR_REVIEW", submission_id="SUB1",
                  allowed_products={"IV1"})
        self.assertEqual(fake.writes(), [])

    def test_a_draft_with_items_this_release_did_not_choose_is_never_submitted(self) -> None:
        for stray in (review_item("X", "inAppPurchaseVersion", "OTHER-IAPv1"),
                      review_item("X", "subscriptionVersion", "OTHER-SUBv1"),
                      review_item("X", "appStoreVersion", "V0-0"),
                      review_item("X", "appAssetLibraryImage", "H")):
            fake = FakeAsc(items=[stray])
            err = io.StringIO()
            with self.subTest(stray=stray["relationships"]), self.assertRaises(SystemExit), \
                    redirect_stdout(io.StringIO()), redirect_stderr(err):
                asc_release.submit_for_review(fake, APP, "V1", "PREPARE_FOR_SUBMISSION", submission_id="SUB1",
                                              allowed_products={"IV1"})
            self.assertIn("holds items this release did not choose (X)", err.getvalue())
            self.assertEqual(fake.submitted, [])

    def test_a_version_draft_must_hold_the_version(self) -> None:
        fake = FakeAsc(items=[review_item("P", "inAppPurchaseVersion", "IV1")])
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit):
            asc_release.check_draft_items(fake, "SUB1", version_id="V1", allowed_products={"IV1"})
        self.assertIn("review submission SUB1 does not hold App Store version V1; not submitting it", err.getvalue())
        held = FakeAsc(items=[review_item("V", "appStoreVersion", "V1"), review_item("P", "inAppPurchaseVersion", "IV1")])
        quiet(asc_release.check_draft_items, held, "SUB1", version_id="V1", allowed_products={"IV1"})

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
        self.assertIn("no asc calls", output)
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

    def test_only_the_abysm_bundle_is_supported(self) -> None:
        code, output = self.run_cli({"UPLOAD_LISTING": "true"}, "--metadata-dir", self.valid_tree(),
                                    "--bundle-id", "com.example.other")
        self.assertEqual(code, 1)
        self.assertIn("only supports the ABYSM iOS bundle", output)

    def test_creative_assets_need_one_image_per_slot(self) -> None:
        self.assertEqual(asc_release.CREATIVE_DIR, ROOT / "store" / "creative" / "ios")
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_cli({"UPLOAD_CREATIVE_ASSETS": "true"}, "--creative-dir", tmp)
            self.assertEqual(code, 1)
            self.assertIn("no header or search results image", output)
            (Path(tmp) / "header").mkdir()
            (Path(tmp) / "header" / "a.png").write_bytes(png_header(width=3840, height=1646))
            (Path(tmp) / "header" / "b.jpg").write_bytes(jpeg_header(3840, 1646))
            code, output = self.run_cli({"UPLOAD_CREATIVE_ASSETS": "true"}, "--creative-dir", tmp)
            self.assertEqual(code, 1)
            self.assertIn("takes one image", output)
            (Path(tmp) / "header" / "b.jpg").unlink()
            (Path(tmp) / "header" / "notes.txt").write_text("not an image")
            code, output = self.run_cli({"UPLOAD_CREATIVE_ASSETS": "true"}, "--creative-dir", tmp)
            self.assertEqual(code, 0, output)
            self.assertIn("creative=True", output)


class MainFlow(unittest.TestCase):
    """Runs asc_release.main() against FakeAsc with a temporary listing, screenshots and creative images."""

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
        self.creative = Path(tmp.name) / "creative"
        for folder, data in (("header", png_header(width=3840, height=1646)),
                             ("search-results", png_header(width=3840, height=2560) + b"search")):
            (self.creative / folder).mkdir(parents=True)
            (self.creative / folder / f"{folder}.png").write_bytes(data)

    def repo_checksums(self) -> dict[str, list[str]]:
        return {kind: [asc_release.md5_hex(p) for p in files] for kind, files in self.shots.items()}

    def image(self, image_id: str, folder: str, state: str) -> dict:
        path = self.creative / folder / f"{folder}.png"
        return {"id": image_id, "attributes": {"fileName": path.name, "fileSize": path.stat().st_size, "state": state,
                                               "createdDate": "2026-10-20"}}

    def run_main(self, fake: FakeAsc, switches: dict[str, str], *args: str, build: bool = True) -> tuple[int, str]:
        argv = ["asc_release.py", "--version", VERSION, "--metadata-dir", str(self.metadata),
                "--creative-dir", str(self.creative), *args]
        if build:
            argv += ["--build-id", "B9", "--build-number", "3"]
        env = {k: v for k, v in os.environ.items() if k not in ASC_FLAGS}
        env.update(switches)
        out = io.StringIO()
        code = 0
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(asc_release, "asc_from_environment", side_effect=fake.open), \
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
CREATIVE = {"UPLOAD_CREATIVE_ASSETS": "true"}
SUBMIT_CALL = ("review", "submissions-submit", "--id", "SUB1", "--confirm")


class LiveSubmitFlowTests(MainFlow):
    def test_selects_rechecks_then_submits(self) -> None:
        fake = FakeAsc()
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.opened, [False])
        calls = fake.calls
        select = calls.index(("versions", "attach-build", "--version-id", "V1", "--build-id", "B9"))
        submit = calls.index(SUBMIT_CALL)
        reads = [i for i, c in enumerate(calls) if c[:2] == ("versions", "view")]
        build_checks = [i for i, c in enumerate(calls) if c[:2] == ("builds", "list")]
        self.assertEqual(len(reads), 3, "checked before selecting, read back, and rechecked")
        self.assertTrue(reads[0] < select < reads[1] < reads[2] < submit)
        self.assertEqual(len(build_checks), 2)
        self.assertTrue(build_checks[1] < reads[2] < submit, "build must be re-verified just before submit")
        self.assertIn(("versions", "update", "--version-id", "V1", "--release-type", "MANUAL"), calls)
        self.assertEqual(items_added(fake), [("appStoreVersions", "V1")])
        self.assertEqual(fake.submitted, ["SUB1"])
        self.assertEqual(fake.writes()[-1], SUBMIT_CALL)

    def test_unlock_goes_out_with_the_version_never_on_its_own(self) -> None:
        fake = FakeAsc(unlock_state="READY_TO_SUBMIT")
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 0, output)
        self.assertEqual(items_added(fake), [("inAppPurchaseVersions", "IV1"), ("appStoreVersions", "V1")])
        self.assertEqual(fake.submitted, ["SUB1"], "one submit sends the version and its products")

    def test_selection_changed_before_submit_aborts_without_any_review_write(self) -> None:
        # Pre-check (1) and read-back (2) see this run's build; the final recheck (3) does not.
        fake = FakeAsc(revert_on_read=3, unlock_state="READY_TO_SUBMIT")
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 1)
        self.assertIn("not submitting", output)
        self.assertEqual(fake.submitted, [])
        # Unlock the Deep only joined the unsubmitted draft; nothing reached App Review.
        self.assertEqual(items_added(fake), [("inAppPurchaseVersions", "IV1")])

    def test_a_product_that_cannot_be_added_keeps_the_version_out_of_review(self) -> None:
        fake = FakeAsc(unlock_state="READY_TO_SUBMIT", refuse_items={"IV1"})
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 1)
        self.assertIn("Not submitting the app version", output)
        self.assertEqual(fake.submitted, [])
        self.assertNotIn(("appStoreVersions", "V1"), items_added(fake))

    def test_a_reused_draft_with_items_this_release_did_not_choose_is_not_submitted(self) -> None:
        fake = FakeAsc(items=[review_item("STRAY", "inAppPurchaseVersion", "OTHER-IAPv1")])
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 1)
        self.assertIn("did not choose (STRAY)", output)
        self.assertEqual(fake.submitted, [])
        # A catalog product's version (in any state) and this version are fine.
        fake = FakeAsc(unlock_versions=[{"id": "IV1", "attributes": {"version": 1, "state": "APPROVED"}}],
                       items=[review_item("OK", "inAppPurchaseVersion", "IV1")])
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.submitted, ["SUB1"])

    def test_a_creative_draft_is_never_used_for_the_version(self) -> None:
        creative = [review_item("IMG", "appAssetLibraryImage", "H")]
        fake = FakeAsc(drafts=("CREATIVE",), draft_items={"CREATIVE": creative})
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 0, output)
        self.assertIn(("review", "submissions-create"), [c[:2] for c in fake.writes()])
        self.assertEqual(fake.submitted, ["NEW"])
        self.assertEqual(fake.items["CREATIVE"], creative)

    def test_a_ready_for_review_version_with_no_draft_holding_it_stops_before_any_write(self) -> None:
        # READY_FOR_REVIEW says a draft holds the version; the only draft here does not.
        # The build is not selected yet and the release type differs, so selecting
        # the build or setting the release type would write.
        for drafts, items in ((("SUB1",), [review_item("P", "inAppPurchaseVersion", "IV1")]), ((), None)):
            fake = FakeAsc(state="READY_FOR_REVIEW", attached="OLD", release_type=None,
                           unlock_state="READY_TO_SUBMIT", drafts=drafts, items=items)
            with self.subTest(drafts=drafts):
                code, output = self.run_main(fake, SUBMIT_ONLY)
                self.assertEqual(code, 1)
                self.assertIn(f"version {VERSION} is READY_FOR_REVIEW, but no draft review submission holds it", output)
                # Checked before the build is selected, so nothing at all is written.
                self.assertEqual(fake.writes(), [])
                self.assertEqual((fake.attached, fake.release_type), ("OLD", None))

    def test_a_stopped_submit_leaves_the_listing_text_alone_too(self) -> None:
        # Text stays editable in READY_FOR_REVIEW, so the draft check must come
        # before the listing update, not just before the build selection.
        for drafts, items in ((("SUB1",), [review_item("P", "inAppPurchaseVersion", "IV1")]), ((), None)):
            fake = FakeAsc(state="READY_FOR_REVIEW", version_text={**LIVE_TEXT, "description": "Old", "whatsNew": "Older"},
                           info_text={"subtitle": "Old"}, drafts=drafts, items=items)
            with self.subTest(drafts=drafts):
                code, output = self.run_main(fake, TEXT_AND_SUBMIT)
                self.assertEqual(code, 1, output)
                self.assertIn(f"version {VERSION} is READY_FOR_REVIEW, but no draft review submission holds it", output)
                self.assertEqual(fake.writes(), [])
                self.assertEqual((fake.version_text["description"], fake.info_text["subtitle"]), ("Old", "Old"))

    def test_the_draft_holding_this_version_is_chosen_over_others(self) -> None:
        other = [review_item("P", "inAppPurchaseVersion", "IV1")]
        mine = [review_item("V", "appStoreVersion", "V1")]
        fake = FakeAsc(state="READY_FOR_REVIEW", attached="B9", release_type="MANUAL", unlock_state="READY_TO_SUBMIT",
                       drafts=("OTHER", "MINE"), draft_items={"OTHER": other, "MINE": mine})
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 0, output)
        self.assertEqual({flag(c, "--submission") for c in fake.writes() if c[:2] == ("review", "items-add")}, {"MINE"})
        self.assertEqual(fake.submitted, ["MINE"])
        self.assertEqual(fake.items["OTHER"], other)

    def test_another_versions_draft_is_never_reused(self) -> None:
        theirs = [review_item("V", "appStoreVersion", "V0-0")]
        fake = FakeAsc(drafts=("THEIRS",), draft_items={"THEIRS": theirs})
        code, output = self.run_main(fake, SUBMIT_ONLY)
        self.assertEqual(code, 0, output)
        self.assertIn(("review", "submissions-create"), [c[:2] for c in fake.writes()])
        self.assertEqual(fake.submitted, ["NEW"])
        self.assertEqual(fake.items["THEIRS"], theirs)

    def test_a_rerun_with_nothing_to_send_leaves_no_empty_draft(self) -> None:
        for state in sorted(asc_release.SUBMITTED_VERSION_STATES):
            fake = FakeAsc(state=state, attached="B9", drafts=())
            with self.subTest(state=state):
                code, output = self.run_main(fake, SUBMIT_ONLY)
                self.assertEqual(code, 0, output)
                self.assertEqual(fake.writes(), [])
                self.assertEqual(fake.drafts, [])

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

    def test_public_release_sets_after_approval(self) -> None:
        fake = FakeAsc()
        code, output = self.run_main(fake, {**SUBMIT_ONLY, "PUBLIC_RELEASE": "true"})
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.release_type, "AFTER_APPROVAL")


class RerunTests(MainFlow):
    """Re-running the store step after a partly finished submission (IOS-REL-3)."""

    IN_DRAFT = [review_item("I1", "appStoreVersion", "V1")]

    def test_ready_for_review_rerun_with_text_switches_submits(self) -> None:
        # The first attempt left the version in the draft with this run's build; its
        # submit failed. Text still matches the repo, so only the submit is sent.
        fake = FakeAsc(state="READY_FOR_REVIEW", attached="B9", release_type="MANUAL", items=self.IN_DRAFT)
        code, output = self.run_main(fake, TEXT_AND_SUBMIT)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.writes(), [SUBMIT_CALL])

    def test_ready_for_review_text_can_still_change(self) -> None:
        fake = FakeAsc(state="READY_FOR_REVIEW", attached="B9", release_type="MANUAL",
                       version_text={**LIVE_TEXT, "whatsNew": "Old"}, items=self.IN_DRAFT)
        code, output = self.run_main(fake, TEXT_AND_SUBMIT)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.writes(), [("localizations", "update", "--id", "LOC-en-US", "--whats-new", "Fixes"), SUBMIT_CALL])

    def test_ready_for_review_screenshots_must_already_match(self) -> None:
        same = FakeAsc(state="READY_FOR_REVIEW", attached="B9", release_type="MANUAL", screenshots=self.repo_checksums(),
                       items=self.IN_DRAFT)
        code, output = self.run_main(same, EVERYTHING)
        self.assertEqual(code, 0, output)
        self.assertEqual(same.writes(), [SUBMIT_CALL])  # the version is already in the draft
        changed = self.repo_checksums()
        changed[IPAD] = list(reversed(changed[IPAD]))
        differs = FakeAsc(state="READY_FOR_REVIEW", attached="B9", release_type="MANUAL", screenshots=changed,
                          items=self.IN_DRAFT)
        code, output = self.run_main(differs, EVERYTHING)
        self.assertEqual(code, 1)
        self.assertIn("screenshots cannot change while the version is READY_FOR_REVIEW", output)
        self.assertEqual(differs.writes(), [])
        # The repo's checksums are not enough: Apple must have processed every image.
        unprocessed = FakeAsc(state="READY_FOR_REVIEW", attached="B9", release_type="MANUAL",
                              screenshots=self.repo_checksums(), items=self.IN_DRAFT,
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
        self.assertEqual(fake.writes(), [("review", "items-add", "--submission", "SUB1", "--item-type", "appStoreVersions",
                                          "--item-id", "V1", "--if-exists", "skip"), SUBMIT_CALL])

    def test_screenshots_with_alpha_stop_before_any_asc_call(self) -> None:
        png(self.shots[IPAD][1], 2752, 2064, color_type=6)
        for mode in (("--preflight",), ()):
            fake = FakeAsc()
            with self.subTest(mode=mode):
                code, output = self.run_main(fake, {"UPLOAD_SCREENSHOTS": "true"}, *mode, build=False)
                self.assertEqual(code, 1, output)
                self.assertIn(f"these screenshots store an alpha channel, which App Store Connect refuses (asc uploads "
                              f"no PNG with alpha, even a fully opaque one): {IPAD}: 01.png", output)
                self.assertEqual(fake.calls, [])
        # The offline dry run reports it without failing.
        fake = FakeAsc()
        code, output = self.run_main(fake, {"UPLOAD_SCREENSHOTS": "true"}, "--dry-run", build=False)
        self.assertEqual(code, 0, output)
        self.assertIn("warning: these screenshots store an alpha channel", output)
        self.assertIn("until then a run with UPLOAD_SCREENSHOTS on stops at its preflight", output)
        # Other switches never read the screenshots.
        code, output = self.run_main(FakeAsc(), {"UPLOAD_LISTING": "true"}, "--preflight", build=False)
        self.assertEqual(code, 0, output)

    def test_a_first_run_uploads_what_differs_and_a_rerun_sends_nothing_new(self) -> None:
        fake = FakeAsc(version_text={**LIVE_TEXT, "description": "Old"}, info_text={"subtitle": "Old"})
        switches = {"UPLOAD_LISTING": "true", "UPLOAD_SCREENSHOTS": "true"}
        code, output = self.run_main(fake, switches, build=False)
        self.assertEqual(code, 0, output)
        self.assertEqual([c[:2] for c in fake.writes()], [("localizations", "update"), ("localizations", "update"),
                                                          ("screenshots", "upload"), ("screenshots", "upload")])
        self.assertEqual([(kind, names) for kind, names in fake.uploads], [(IPHONE, ["00.png", "01.png"]),
                                                                           (IPAD, ["00.png", "01.png"])])
        writes = len(fake.writes())
        code, output = self.run_main(fake, switches, build=False)
        self.assertEqual(code, 0, output)
        self.assertEqual(len(fake.writes()), writes)


class PreflightTests(MainFlow):
    """`asc_release.py --preflight`: asc in read-only mode, before anything is built (IOS-REL-2)."""

    def preflight(self, fake: FakeAsc, switches: dict[str, str]) -> tuple[int, str]:
        code, output = self.run_main(fake, switches, "--preflight", build=False)
        self.assertEqual(fake.opened, [True], "the preflight must run asc read-only")
        self.assertEqual(fake.writes(), [], "the preflight must never change App Store Connect")
        return code, output

    def test_missing_version_fails_with_the_fix(self) -> None:
        code, output = self.preflight(FakeAsc(version_exists=False), {"UPLOAD_LISTING": "true"})
        self.assertEqual(code, 1)
        self.assertIn("turn on IOS_CREATE_VERSION, or create the version in App Store Connect first", output)

    def test_ready_version_passes_and_reports_what_would_change(self) -> None:
        fake = FakeAsc(version_text={**LIVE_TEXT, "description": "Old"}, unlock_state="READY_TO_SUBMIT")
        code, output = self.preflight(fake, {**EVERYTHING, **CREATIVE})
        self.assertEqual(code, 0, output)
        self.assertIn("would update description", output)
        self.assertIn("would replace", output)
        self.assertIn("would upload header.png to the Asset Library and send it to App Review", output)
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
        self.assertIn(f"{IPAD}-1.png: FAILED", output)

    def test_creative_images_are_checked_without_writing(self) -> None:
        fake = FakeAsc(library=[self.image("H", "header", "APPROVED"),
                                self.image("S", "search-results", "PREPARE_FOR_SUBMISSION")])
        code, output = self.preflight(fake, CREATIVE)
        self.assertEqual(code, 0, output)
        self.assertIn("would place header.png on the product page", output)
        self.assertIn("would send search-results.png to App Review", output)

    def test_states_and_inputs_that_would_stop_the_store_step_fail_early(self) -> None:
        cases = {
            "live version": (FakeAsc(state="READY_FOR_SALE"), {"UPLOAD_LISTING": "true"}, "not editable"),
            "live version, creative": (FakeAsc(state="READY_FOR_SALE"), CREATIVE, "not editable"),
            "approved version, submit": (FakeAsc(state="PENDING_DEVELOPER_RELEASE"), SUBMIT_ONLY, "cannot be submitted"),
            "unlock without a version": (FakeAsc(unlock_state="READY_TO_SUBMIT", unlock_versions=[]), SUBMIT_ONLY,
                                         "cannot be added to App Review"),
            "locale missing in App Store Connect": (FakeAsc(locales=("de-DE",)), {"UPLOAD_WHATS_NEW": "true"},
                                                    "no en-US localization"),
            "App Info locked": (FakeAsc(state="READY_FOR_REVIEW", info_text={"subtitle": "Old"}),
                                {"UPLOAD_LISTING": "true"}, "no App Info is editable"),
            "creative image rejected": (FakeAsc(library=[self.image("H", "header", "REJECTED")]), CREATIVE,
                                        "App Review rejected header.png"),
            "creative image while locked": (FakeAsc(state="READY_FOR_REVIEW"), CREATIVE,
                                            "cannot upload the product page header image header.png while the "
                                            "version is READY_FOR_REVIEW"),
        }
        for label, (fake, switches, message) in cases.items():
            if label == "App Info locked":
                fake.info_state = lambda: "WAITING_FOR_REVIEW"  # type: ignore[method-assign]
            with self.subTest(label):
                code, output = self.preflight(fake, switches)
                self.assertEqual(code, 1, output)
                self.assertIn(message, output)

    def test_versions_the_store_step_can_use_pass(self) -> None:
        held = [review_item("I", "appStoreVersion", "V1")]
        for state in sorted(asc_release.SUBMITTABLE_VERSION_STATES):
            with self.subTest(state=state):
                fake = FakeAsc(state=state, drafts=("D1",), draft_items={"D1": held})
                code, output = self.preflight(fake, {**SUBMIT_ONLY, "UPLOAD_LISTING": "true"})
                self.assertEqual(code, 0, output)

    def test_a_ready_for_review_version_needs_its_draft_before_the_build(self) -> None:
        other = [review_item("P", "inAppPurchaseVersion", "IV1")]
        for drafts, items in (((), {}), (("D1",), {"D1": other})):
            fake = FakeAsc(state="READY_FOR_REVIEW", drafts=drafts, draft_items=items)
            with self.subTest(drafts=drafts):
                code, output = self.preflight(fake, SUBMIT_ONLY)
                self.assertEqual(code, 1, output)
                self.assertIn("no draft review submission holds it", output)
        # Without review submission the draft does not matter.
        code, output = self.preflight(FakeAsc(state="READY_FOR_REVIEW", drafts=()), {"UPLOAD_LISTING": "true"})
        self.assertEqual(code, 0, output)

    def test_preflight_needs_no_build_and_dry_run_is_separate(self) -> None:
        code, output = self.preflight(FakeAsc(), SUBMIT_ONLY)
        self.assertEqual(code, 0, output)
        fake = FakeAsc()
        code, output = self.run_main(fake, {"UPLOAD_LISTING": "true"}, "--preflight", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("separate modes", output)
        self.assertEqual(fake.calls, [])

    def test_a_write_in_read_only_mode_never_reaches_app_store_connect(self) -> None:
        # asc refuses every write while ASC_READ_ONLY is set (exit 6); the fake does the same.
        fake = FakeAsc().open(read_only=True)
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit):
            asc_release.call(fake, "versions", "update", "--version-id", "V1", "--release-type", "MANUAL")
        self.assertIn("exit 6", err.getvalue())
        self.assertIsNone(fake.release_type)


class CreateVersionTests(unittest.TestCase):
    """`asc_release.py --create-version` (IOS_CREATE_VERSION): add the tag's App Store version only when missing."""

    ON = {"CREATE_IOS_VERSION": "true"}

    def create(self, fake: FakeAsc, flags: dict[str, str] | None = None, *args: str,
               version: str | None = VERSION) -> tuple[int, str]:
        argv = ["asc_release.py", "--create-version", *(["--version", version] if version else []), *args]
        env = {k: v for k, v in os.environ.items() if k not in ASC_FLAGS}
        env.update(self.ON if flags is None else flags)
        out = io.StringIO()
        code = 0
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(asc_release, "asc_from_environment", side_effect=fake.open), \
                redirect_stdout(out), redirect_stderr(out):
            try:
                asc_release.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue()

    CREATE = ("versions", "create", "--app", APP, "--version", VERSION, "--platform", "IOS")

    def test_switch_off_makes_no_calls(self) -> None:
        fake = FakeAsc(version_exists=False)
        code, output = self.create(fake, {})
        self.assertEqual(code, 0, output)
        self.assertIn("skipped", output)
        self.assertEqual(fake.calls, [])

    def test_existing_version_is_left_alone(self) -> None:
        fake = FakeAsc(state="READY_FOR_REVIEW")
        code, output = self.create(fake)
        self.assertEqual(code, 0, output)
        self.assertIn(f"App Store version {VERSION} already exists (READY_FOR_REVIEW)", output)
        self.assertEqual(fake.writes(), [])

    def test_missing_version_is_created_for_abysm_and_read_back(self) -> None:
        fake = FakeAsc(version_exists=False)
        code, output = self.create(fake)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.opened, [False])
        self.assertEqual(fake.calls[0], ("apps", "view", "--id", APP))  # the pinned app is checked first
        self.assertEqual(fake.writes(), [self.CREATE])
        self.assertEqual(fake.calls[-1][:2], ("versions", "list"), "the created version must be read back")
        self.assertIn(f"created App Store version {VERSION} (PREPARE_FOR_SUBMISSION)", output)

    def test_a_created_version_that_does_not_read_back_once_fails_naming_it(self) -> None:
        # Not listed yet (0 records) or listed twice (2 records): the run stops and
        # points at App Store Connect, not at the switch that is already on.
        for listed in (0, 2):
            with self.subTest(listed=listed):
                fake = FakeAsc(version_exists=False, created_records=listed)
                code, output = self.create(fake)
                self.assertEqual(code, 1)
                self.assertIn(f"created App Store version {VERSION}, but reading it back found {listed} records; "
                              "check it in App Store Connect before rerunning", output)
                self.assertNotIn("turn on IOS_CREATE_VERSION", output)
                self.assertEqual(fake.writes(), [self.CREATE])

    def test_another_version_on_its_way_blocks_creation(self) -> None:
        for state in ("PREPARE_FOR_SUBMISSION", "WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_DEVELOPER_RELEASE",
                      "REJECTED", ""):
            with self.subTest(state=state):
                fake = FakeAsc(version_exists=False,
                               other_versions=[("0.9", "REPLACED_WITH_NEW_VERSION"), ("1.0", state)])
                code, output = self.create(fake)
                self.assertEqual(code, 1)
                self.assertIn(f"version '1.0' is still {state or 'in an unknown state'}", output)
                self.assertIn("nothing was changed", output)
                self.assertNotIn("not newer", output)
                self.assertEqual(fake.writes(), [])

    def test_version_not_newer_than_an_existing_one_is_refused(self) -> None:
        for existing in ("1.1", "1.0.10", "2"):
            with self.subTest(existing=existing):
                fake = FakeAsc(version_exists=False, other_versions=[(existing, "READY_FOR_SALE")])
                code, output = self.create(fake)
                self.assertEqual(code, 1)
                self.assertIn(f"version {VERSION} is not newer than the existing version {existing}", output)
                self.assertEqual(fake.writes(), [])

    def test_older_finished_versions_allow_creation(self) -> None:
        finished = [("0.7", "DEVELOPER_REMOVED_FROM_SALE"), ("0.8", "REMOVED_FROM_SALE"),
                    ("0.9", "REPLACED_WITH_NEW_VERSION"), ("1.0", "READY_FOR_SALE")]
        self.assertEqual({state for _, state in finished}, asc_release.FINISHED_VERSION_STATES)
        fake = FakeAsc(version_exists=False, other_versions=finished)
        code, output = self.create(fake)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.writes(), [self.CREATE])

    def test_other_app_ambiguous_or_bad_version_fails_without_writing(self) -> None:
        fake = FakeAsc(bundle="com.example.other", version_exists=False)
        code, output = self.create(fake)
        self.assertEqual(code, 1)
        self.assertIn(f"expected {BUNDLE}", output)
        self.assertEqual(fake.writes(), [])
        fake = FakeAsc(other_versions=[(VERSION, "PREPARE_FOR_SUBMISSION")])
        code, output = self.create(fake)
        self.assertEqual(code, 1)
        self.assertIn("ambiguous", output)
        self.assertEqual(fake.writes(), [])
        for bad in ("1.0.1-beta", "v1.0.1", "1.0.1.2", "1.x", "١.٠"):
            with self.subTest(bad=bad):
                fake = FakeAsc(version_exists=False)
                code, output = self.create(fake, version=bad)
                self.assertEqual(code, 1)
                self.assertIn("must look like 1.0 or 1.0.1", output)
                self.assertEqual(fake.calls, [])

    def test_dry_run_rejects_a_bad_version_like_a_live_run(self) -> None:
        for bad in ("1.0.1-beta", "v1.0.1", "1.0.1.2", "١.٠"):
            with self.subTest(bad=bad):
                fake = FakeAsc(version_exists=False)
                code, output = self.create(fake, None, "--dry-run", version=bad)
                self.assertEqual(code, 1)
                self.assertIn("must look like 1.0 or 1.0.1", output)
                self.assertNotIn("would create", output)
                self.assertEqual(fake.calls, [])

    def test_dry_run_preflight_and_missing_version_make_no_calls(self) -> None:
        fake = FakeAsc(version_exists=False)
        code, output = self.create(fake, None, "--dry-run")
        self.assertEqual(code, 0, output)
        self.assertIn(f"would create App Store version {VERSION}", output)
        code, output = self.create(fake, None, "--preflight")
        self.assertEqual(code, 1)
        self.assertIn("separate modes", output)
        code, output = self.create(fake, version=None)
        self.assertEqual(code, 1)
        self.assertIn("--create-version needs --version", output)
        self.assertEqual(fake.calls, [])


class CreativeAssetTests(MainFlow):
    """IOS_UPLOAD_CREATIVE_ASSETS: the product page header and search results images."""

    def run_creative(self, fake: FakeAsc) -> tuple[int, str]:
        return self.run_main(fake, CREATIVE, build=False)

    def test_new_images_are_uploaded_and_reviewed_on_their_own(self) -> None:
        fake = FakeAsc(drafts=())
        code, output = self.run_creative(fake)
        self.assertEqual(code, 0, output)
        uploads = [c for c in fake.writes() if c[:3] == ("asset-library", "images", "upload")]
        self.assertEqual([Path(flag(c, "--file")).name for c in uploads], ["header.png", "search-results.png"])
        self.assertTrue(all(flag(c, "--library-id") == "LIB1" for c in uploads))
        review = [c for c in fake.writes() if c[:1] == ("review",)]
        self.assertEqual([c[:2] for c in review], [("review", "submissions-create"), ("review", "items-add"),
                                                   ("review", "items-add"), ("review", "submissions-submit")])
        self.assertEqual(items_added(fake), [("appAssetLibraryImages", "IMG1"), ("appAssetLibraryImages", "IMG2")])
        self.assertFalse([c for c in fake.writes() if c[:2] == ("localizations", "placements")])
        self.assertEqual(fake.submitted, ["NEW"])

    def test_images_never_take_the_empty_draft_the_version_chose(self) -> None:
        # The version's draft is picked first; an empty leftover draft goes to the
        # version, and the images get a submission of their own.
        fake = FakeAsc(drafts=("EMPTY",))
        code, output = self.run_main(fake, {**CREATIVE, **SUBMIT_ONLY})
        self.assertEqual(code, 0, output)
        submitted = [flag(c, "--id") for c in fake.writes() if c[:2] == ("review", "submissions-submit")]
        self.assertEqual(len(submitted), 2)
        self.assertEqual(submitted[-1], "EMPTY")
        image_items = {flag(c, "--submission") for c in fake.writes()
                       if c[:2] == ("review", "items-add") and flag(c, "--item-type") == "appAssetLibraryImages"}
        self.assertEqual(image_items, {submitted[0]})
        self.assertNotIn("EMPTY", image_items)

    def test_a_rerun_finishes_the_empty_draft_an_interrupted_review_left(self) -> None:
        # A run stopped between creating its draft and adding the images; the
        # rerun uses that draft instead of leaving it behind and starting another.
        fake = FakeAsc(drafts=("EMPTY",))
        code, output = self.run_creative(fake)
        self.assertEqual(code, 0, output)
        self.assertNotIn(("review", "submissions-create"), [c[:2] for c in fake.writes()])
        self.assertEqual(fake.submitted, ["EMPTY"])
        # A draft already holding some of the images is finished before an empty one.
        library = [self.image("H", "header", "PREPARE_FOR_SUBMISSION"),
                   self.image("S", "search-results", "PREPARE_FOR_SUBMISSION")]
        held = [review_item("I-H", "appAssetLibraryImage", "H")]
        fake = FakeAsc(library=library, drafts=("EMPTY", "PART"), draft_items={"PART": held})
        code, output = self.run_creative(fake)
        self.assertEqual(code, 0, output)
        self.assertEqual({flag(c, "--submission") for c in fake.writes() if c[:2] == ("review", "items-add")}, {"PART"})
        self.assertEqual(fake.submitted, ["PART"])
        self.assertEqual(fake.items["EMPTY"], [])

    def test_an_interrupted_upload_is_uploaded_again(self) -> None:
        # asc never deletes the reservation an interrupted upload leaves behind.
        fake = FakeAsc(drafts=(), library=[self.image("STALE", "header", "AWAITING_UPLOAD")])
        code, output = self.run_creative(fake)
        self.assertEqual(code, 0, output)
        uploads = [Path(flag(c, "--file")).name for c in fake.writes() if c[:3] == ("asset-library", "images", "upload")]
        self.assertEqual(uploads, ["header.png", "search-results.png"])
        self.assertNotIn("STALE", [item_id for _, item_id in items_added(fake)])
        self.assertIn("AWAITING_UPLOAD", asc_release.CREATIVE_DEAD_STATES)

    def test_images_in_review_are_neither_reuploaded_nor_placed(self) -> None:
        fake = FakeAsc(library=[self.image("H", "header", "WAITING_FOR_REVIEW"),
                                self.image("S", "search-results", "IN_REVIEW")])
        code, output = self.run_creative(fake)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.writes(), [])
        self.assertIn("it is placed once App Review approves it", output)

    def test_approved_images_are_placed_and_existing_ones_swapped(self) -> None:
        old = {"id": "PL-old", "attributes": {"placementType": "PRODUCT_PAGE_HEADER_ASSET"},
               "relationships": {"image": {"data": {"id": "OLDIMG"}}}}
        fake = FakeAsc(library=[self.image("H", "header", "APPROVED"), self.image("S", "search-results", "APPROVED")],
                       placements=[old])
        code, output = self.run_creative(fake)
        self.assertEqual(code, 0, output)
        swap = [c for c in fake.writes() if c[:3] == ("localizations", "placements", "swap")][0]
        self.assertEqual((flag(swap, "--localization-id"), flag(swap, "--image-id"), flag(swap, "--placement-id")),
                         ("LOC-en-US", "H", "PL-old"))
        self.assertIn("--confirm", swap)
        create = [c for c in fake.writes() if c[:3] == ("localizations", "placements", "create")][0]
        self.assertEqual((flag(create, "--image-id"), flag(create, "--placement-type"), flag(create, "--placement-group")),
                         ("S", "APP_STORE_SEARCH_RESULTS_ASSET", "DEFAULT_PROFILE"))
        # A second run finds both placed and writes nothing.
        writes = len(fake.writes())
        code, output = self.run_creative(fake)
        self.assertEqual(code, 0, output)
        self.assertEqual(len(fake.writes()), writes)

    def test_an_image_with_alpha_fails_before_any_call(self) -> None:
        (self.creative / "header" / "header.png").write_bytes(png_header(6))
        for mode in ((), ("--preflight",), ("--dry-run",)):
            fake = FakeAsc()
            with self.subTest(mode=mode):
                code, output = self.run_main(fake, CREATIVE, *mode, build=False)
                self.assertEqual(code, 1, output)
                self.assertIn("the product page header image header.png has an alpha channel, which App Store Connect "
                              "refuses; re-export it as RGB", output)
                self.assertEqual(fake.calls, [])

    def test_images_apple_would_refuse_fail_before_any_call(self) -> None:
        cases = {
            "header": [png_header(width=3840, height=2160), jpeg_header(3840, 1646), b"not an image"],
            "search-results": [png_header(width=3000, height=2001), png_header(width=1800, height=1200),
                               jpeg_header(4000, 2666)],
        }
        for folder, contents in cases.items():
            path = self.creative / folder / f"{folder}.png"
            original = path.read_bytes()
            for content in contents:
                path.write_bytes(content)
                for mode in ((), ("--dry-run",)):
                    fake = FakeAsc()
                    with self.subTest(folder=folder, content=content[:24], mode=mode):
                        code, output = self.run_main(fake, CREATIVE, *mode, build=False)
                        self.assertEqual(code, 1, output)
                        self.assertIn(f"image {folder}.png is", output)
                        self.assertEqual(fake.calls, [])
            path.write_bytes(original)

    def test_sizes_apple_accepts_pass(self) -> None:
        good = [("PRODUCT_PAGE_HEADER_ASSET", png_header(width=3840, height=1646)),
                ("PRODUCT_PAGE_HEADER_ASSET", png_header(width=5244, height=2950)),
                ("APP_STORE_SEARCH_RESULTS_ASSET", png_header(width=3840, height=2560)),
                ("APP_STORE_SEARCH_RESULTS_ASSET", jpeg_header(1920, 1280)),
                ("APP_STORE_SEARCH_RESULTS_ASSET", png_header(width=5244, height=2950))]
        for placement, content in good:
            path = self.creative / "probe"
            path.write_bytes(content)
            with self.subTest(placement=placement, content=content[:24]):
                self.assertIsNone(asc_release.creative_size_problem(placement, path))
        self.assertEqual(asc_release.image_dimensions(path), ("png", 5244, 2950))

    def test_an_approved_image_on_a_locked_version_waits_without_failing(self) -> None:
        # Approval can land between the submit and a rerun of the store job.
        library = [self.image("H", "header", "APPROVED"), self.image("S", "search-results", "IN_REVIEW")]
        for state in sorted(asc_release.SUBMITTED_VERSION_STATES | {"READY_FOR_REVIEW"}):
            fake = FakeAsc(state=state, attached="B9", library=library)
            with self.subTest(state=state):
                code, output = self.run_creative(fake)
                self.assertEqual(code, 0, output)
                self.assertEqual(fake.writes(), [])
                self.assertIn("header.png is approved; it is placed on a later run, once the version can be edited",
                              output)
        # The preflight reports it the same way.
        fake = FakeAsc(state="WAITING_FOR_REVIEW", attached="B9", library=library)
        code, output = self.run_main(fake, CREATIVE, "--preflight", build=False)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.writes(), [])

    def test_a_rejected_image_stops_the_run(self) -> None:
        fake = FakeAsc(library=[self.image("H", "header", "REJECTED")])
        code, output = self.run_creative(fake)
        self.assertEqual(code, 1)
        self.assertIn("App Review rejected header.png; replace the image (a new file name)", output)
        self.assertEqual(fake.writes(), [])

    def test_a_locked_version_takes_no_new_images(self) -> None:
        fake = FakeAsc(state="WAITING_FOR_REVIEW", attached="B9")
        code, _ = self.run_creative(fake)
        self.assertEqual(code, 1)
        self.assertEqual(fake.writes(), [])

    def test_a_locked_version_sends_nothing_to_review(self) -> None:
        for state in ("WAITING_FOR_REVIEW", "IN_REVIEW", "READY_FOR_REVIEW"):
            for image_state in ("UPLOAD_COMPLETE", "PREPARE_FOR_SUBMISSION"):
                fake = FakeAsc(state=state, attached="B9", library=[self.image("H", "header", image_state)])
                with self.subTest(state=state, image_state=image_state):
                    code, output = self.run_creative(fake)
                    self.assertEqual(code, 1, output)
                    self.assertIn(f"cannot send the product page header image header.png to App Review while the "
                                  f"version is {state}", output)
                    self.assertEqual(fake.writes(), [])

    def test_a_locked_version_passes_when_its_images_are_in_place(self) -> None:
        placed = [{"id": f"PL-{image}", "attributes": {"placementType": placement},
                   "relationships": {"image": {"data": {"id": image}}}}
                  for image, placement in (("H", "PRODUCT_PAGE_HEADER_ASSET"), ("S", "APP_STORE_SEARCH_RESULTS_ASSET"))]
        library = [self.image("H", "header", "APPROVED"), self.image("S", "search-results", "WAITING_FOR_REVIEW")]
        for state in sorted(asc_release.SUBMITTED_VERSION_STATES | {"READY_FOR_REVIEW"}):
            fake = FakeAsc(state=state, library=library, placements=placed)
            with self.subTest(state=state):
                code, output = self.run_creative(fake)
                self.assertEqual(code, 0, output)
                self.assertEqual(fake.writes(), [])

    def test_a_retry_finishes_the_creative_draft_it_left_behind(self) -> None:
        library = [self.image("H", "header", "PREPARE_FOR_SUBMISSION"),
                   self.image("S", "search-results", "PREPARE_FOR_SUBMISSION")]
        fake = FakeAsc(library=library, drafts=("OLD",), draft_items={"OLD": [review_item("I-H", "appAssetLibraryImage", "H")]})
        code, output = self.run_creative(fake)
        self.assertEqual(code, 0, output)
        self.assertNotIn(("review", "submissions-create"), [c[:2] for c in fake.writes()])
        self.assertEqual(items_added(fake), [("appAssetLibraryImages", "H"), ("appAssetLibraryImages", "S")])
        self.assertEqual(fake.submitted, ["OLD"])
        # A draft holding anything else is left alone and a new one is used.
        other = [review_item("X", "appStoreVersion", "V1")]
        fake = FakeAsc(library=library, drafts=("VERSION",), draft_items={"VERSION": other})
        code, output = self.run_creative(fake)
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.submitted, ["NEW"])
        self.assertEqual(fake.items["VERSION"], other)

    def test_a_creative_submission_with_other_items_is_not_submitted(self) -> None:
        fake = FakeAsc(drafts=())
        original = fake.run

        def run(*args: str, **kwargs: object):
            result = original(*args, **kwargs)
            if args[:2] == ("review", "submissions-create"):
                fake.items[result["data"]["id"]].append(review_item("X", "appStoreVersion", "V1"))
            return result

        fake.run = run  # type: ignore[method-assign]
        code, output = self.run_creative(fake)
        self.assertEqual(code, 1)
        self.assertIn("holds unexpected items ['X']; not submitting it", output)
        self.assertEqual(fake.submitted, [])


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

    def test_exports_the_version_text_and_app_info_with_asc_read_only(self) -> None:
        fake = FakeAsc(version_text={"description": "Desc", "keywords": "k", "whatsNew": "Fixes"},
                       info_text={"name": "ABYSM", "subtitle": "Sub"}, locales=("de-DE", "en-US"))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(asc_release, "asc_from_environment", side_effect=fake.open), \
                mock.patch.object(sys, "argv", ["export_listing.py", "--version", VERSION, "--out", tmp]), \
                redirect_stdout(io.StringIO()):
            export_listing.main()
            ios = Path(tmp) / "ios"
            self.assertEqual(sorted(p.name for p in ios.iterdir()), ["de-DE", "en-US"])
            self.assertEqual(sorted(p.name for p in (ios / "en-US").iterdir()),
                             ["description.txt", "keywords.txt", "name.txt", "subtitle.txt", "whats_new.txt"])
            self.assertEqual((ios / "en-US" / "whats_new.txt").read_text(), "Fixes\n")
            self.assertEqual((ios / "de-DE" / "subtitle.txt").read_text(), "Sub\n")
        self.assertEqual(fake.opened, [True])
        self.assertEqual(fake.writes(), [])
        # The version being prepared is exported with its own (editable) App Info, not the live one.
        info_reads = [c for c in fake.calls if c[:2] == ("localizations", "list") and "app-info" in c]
        self.assertEqual([flag(c, "--app-info") for c in info_reads], ["INFO"])


# Stand-ins for `xcrun simctl` and `sleep` in IosTestScriptTests (no simulator).
# Each `simctl list devices --json` reports the next state from fake.json's
# "reads" (the last one repeats; null means simctl does not list the simulator),
# `simctl shutdown SIM` exits with "shutdown_exit", and every call is recorded.
FAKE_XCRUN = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path

state_file = Path(__file__).with_name("fake.json")
fake = json.loads(state_file.read_text())
args = sys.argv[1:]
fake["calls"].append(" ".join(args))
code = 0
if args == ["simctl", "list", "devices", "--json"]:
    state = fake["reads"].pop(0) if len(fake["reads"]) > 1 else fake["reads"][0]
    devices = [{"udid": "OTHER", "name": "A developer's iPhone", "state": "Booted"}]
    if state is not None:
        devices.append({"udid": "SIM", "name": "ABYSM CI", "state": state})
    print(json.dumps({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-27-0": devices}}))
elif args == ["simctl", "shutdown", "SIM"]:
    code = fake["shutdown_exit"]
else:
    code = 64
state_file.write_text(json.dumps(fake))
sys.exit(code)
'''
FAKE_SLEEP = '#!/bin/sh\necho "$1" >> "$(dirname "$0")/sleeps"\n'


class IosTestScriptTests(unittest.TestCase):
    """scripts/test-ios.sh: the simulator is shut down, and confirmed shut down, between the suites."""

    SCRIPT = (ROOT / "scripts" / "test-ios.sh").read_text()

    def shut_down(self, reads: list[str | None], *, shutdown_exit: int = 0) -> tuple[subprocess.CompletedProcess,
                                                                                    list[str], list[str]]:
        """Run the script's shut_down_simulator() under its own shell options against the fakes."""
        functions = [re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", self.SCRIPT, re.M | re.S)
                     for name in ("simulator_state", "shut_down_simulator")]
        self.assertTrue(all(functions), "simulator_state() and shut_down_simulator() in scripts/test-ios.sh")
        with tempfile.TemporaryDirectory() as tmp:
            fakes = Path(tmp)
            (fakes / "fake.json").write_text(json.dumps({"reads": reads, "shutdown_exit": shutdown_exit, "calls": []}))
            for name, body in (("xcrun", FAKE_XCRUN), ("sleep", FAKE_SLEEP)):
                (fakes / name).write_text(body)
                (fakes / name).chmod(0o755)
            harness = "\n".join([
                re.search(r"^set -euo pipefail$", self.SCRIPT, re.M).group(0),
                "simulator_id=SIM",
                *(function.group(0) for function in functions),
                "if shut_down_simulator; then echo SHUT_DOWN; else echo NOT_SHUT_DOWN; fi",
            ])
            result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=120, check=False,
                                    env=dict(os.environ, PATH=f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}"))
            calls = json.loads((fakes / "fake.json").read_text())["calls"]
            sleeps = (fakes / "sleeps").read_text().split() if (fakes / "sleeps").exists() else []
        return result, calls, sleeps

    def test_the_ui_tests_start_only_after_the_simulator_is_shut_down(self) -> None:
        self.assertIn("run_bundle AbysmTests UnitTests || status=1\n\nshut_down_simulator || exit 1\n\n"
                      "run_bundle AbysmUITests UITests || status=1\n", self.SCRIPT)
        # The old check listed the simulator's launchd jobs, which fails once the
        # simulator is shut down, and read that failure as "the app is gone".
        self.assertNotIn("launchctl", self.SCRIPT)

    def test_a_booted_or_shutting_down_simulator_is_waited_for_until_shut_down(self) -> None:
        # Read before the shutdown, then polled: still going down once, then shut down.
        for before, shutdown_exit in (("Booted", 0), ("Shutting Down", 149)):
            with self.subTest(before=before):
                result, calls, sleeps = self.shut_down([before, before, "Shutdown"], shutdown_exit=shutdown_exit)
                self.assertEqual((result.returncode, result.stdout.splitlines()[-1]), (0, "SHUT_DOWN"), result.stderr)
                self.assertIn(f"state after the unit tests: {before}", result.stdout)
                self.assertIn("simctl shutdown SIM", calls)
                self.assertEqual(sleeps, ["0.5"])

    def test_a_simulator_xcodebuild_already_shut_down_is_ready_at_once(self) -> None:
        # simctl refuses to shut down a shut-down simulator (exit 149); that is fine.
        result, calls, sleeps = self.shut_down(["Shutdown"], shutdown_exit=149)
        self.assertEqual((result.returncode, result.stdout.splitlines()[-1]), (0, "SHUT_DOWN"), result.stderr)
        self.assertIn("state after the unit tests: Shutdown", result.stdout)
        self.assertEqual(sleeps, [])

    def test_a_simulator_that_does_not_shut_down_stops_the_run(self) -> None:
        result, _, sleeps = self.shut_down(["Booted"])
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "NOT_SHUT_DOWN"), result.stderr)
        self.assertIn("still Booted, not shut down; not starting the UI tests", result.stderr)
        self.assertEqual(len(sleeps), 60)

    def test_a_simulator_simctl_does_not_list_stops_the_run(self) -> None:
        result, calls, _ = self.shut_down([None])
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "NOT_SHUT_DOWN"), result.stderr)
        self.assertIn("simctl lists 0 simulators with id SIM", result.stderr)
        self.assertNotIn("simctl shutdown SIM", calls)


class WorkflowWiringTests(unittest.TestCase):
    WORKFLOW = (ROOT / ".github" / "workflows" / "ios-release.yml").read_text()
    INSTALL = "Install the pinned App Store Connect CLI"
    ASC_INSTALL = 'python3 scripts/store/asc_cli.py install --dest "$RUNNER_TEMP/asc-bin"'
    ASC_CHECK = 'PATH="$RUNNER_TEMP/asc-bin:$PATH" python3 scripts/store/asc_cli.py check'

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
        for name, output in (("UPLOAD_LISTING", "listing"), ("UPLOAD_WHATS_NEW", "whats_new"),
                             ("UPLOAD_SCREENSHOTS", "screenshots"), ("UPLOAD_CREATIVE_ASSETS", "creative"),
                             ("SUBMIT_IOS_REVIEW", "submit"), ("PUBLIC_RELEASE", "public_release")):
            self.assertIn(f"{name}: ${{{{ steps.gates.outputs.{output} }}}}", preflight)
        self.assertNotIn("--build-id", preflight)
        install = prepare.index(f"      - name: {self.INSTALL}\n")
        self.assertIn("if: >- steps.gates.outputs.build == 'true' || steps.gates.outputs.asc == 'true' || "
                      "steps.gates.outputs.create_version == 'true'",
                      " ".join(self.step("prepare", self.INSTALL).split()))
        self.assertLess(install, prepare.index("Check the App Store version (read-only preflight)"))
        self.assertLess(prepare.index("--preflight"), prepare.index("ios_release.py build-number"))
        self.assertIn("needs.prepare.result == 'success'", self.job("build"))  # the build waits for it
        self.assertEqual(gates({}, event="workflow_dispatch", ref="main")["asc"], False)

    def test_app_store_version_is_created_before_the_preflight_on_tag_runs_only(self) -> None:
        prepare = self.job("prepare")
        create = self.step("prepare", "Create the App Store version if it is missing (IOS_CREATE_VERSION)")
        self.assertIn("if: steps.gates.outputs.mode == 'release' && steps.gates.outputs.create_version == 'true'", create)
        self.assertIn('python3 -u scripts/store/asc_release.py --create-version --version "$MARKETING_VERSION"', create)
        self.assertIn("CREATE_IOS_VERSION: ${{ steps.gates.outputs.create_version }}", create)
        self.assertIn("MARKETING_VERSION: ${{ steps.gates.outputs.marketing_version }}", create)
        for name in ("APP_STORE_CONNECT_API_KEY_ID", "APP_STORE_CONNECT_ISSUER_ID", "APP_STORE_CONNECT_API_KEY_P8"):
            self.assertIn(f"{name}: ${{{{ secrets.{name} }}}}", create)
        self.assertIn("create_version: ${{ steps.gates.outputs.create_version }}", prepare)
        self.assertEqual(self.WORKFLOW.count("--create-version"), 1)
        # After the offline checks and the tooling install, before the preflight and any build.
        position = prepare.index("--create-version")
        self.assertLess(prepare.index("asc_release.py --dry-run"), position)
        self.assertLess(prepare.index(f"      - name: {self.INSTALL}\n"), position)
        self.assertLess(position, prepare.index("asc_release.py --preflight"))
        self.assertLess(position, prepare.index("ios_release.py build-number"))
        self.assertIn("steps.gates.outputs.create_version == 'true'", self.step("prepare", self.INSTALL))
        # Validation runs resolve it off whatever the switches say.
        self.assertFalse(gates(ALL_ON, event="workflow_dispatch", ref="main")["create_version"])

    def test_export_compliance_is_checked_before_the_build_and_in_the_archive(self) -> None:
        build = self.job("build")
        verify = self.step("build", "Verify app identity and version in every bundle")
        command = 'python3 scripts/store/ios_release.py export-compliance --info-plist "$main/Info.plist"'
        self.assertIn(command, verify)
        self.assertIn("/scripts/store/ios_release.py", build)  # in the build job's sparse checkout
        # After the archive, before anything is exported, validated or uploaded.
        self.assertLess(build.index("      - name: Archive Release\n"), build.index(command))
        self.assertLess(build.index(command), build.index("      - name: Write export options\n"))
        # The gates step reads the project's answer before anything is built, so
        # prepare (and the pull request checks) need the app's Info.plist.
        self.assertIn("/Abysm/Info.plist", self.job("prepare"))
        checks = (ROOT / ".github" / "workflows" / "store-checks.yml").read_text()
        self.assertIn("            /Abysm/Info.plist\n", checks)
        self.assertEqual(checks.count("      - 'Abysm/Info.plist'\n"), 2)

    def test_unused_store_assets_never_block_a_release(self) -> None:
        offline = self.step("prepare", "Check the release tooling and inputs (offline)")
        self.assertIn("STORE_TESTS_SCOPE: release", offline)
        # The listing/screenshot checks a release does run are the gated dry run's.
        self.assertIn("UPLOAD_LISTING: ${{ steps.gates.outputs.listing }}", offline)
        self.assertIn("UPLOAD_SCREENSHOTS: ${{ steps.gates.outputs.screenshots }}", offline)
        self.assertIn("UPLOAD_CREATIVE_ASSETS: ${{ steps.gates.outputs.creative }}", offline)
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
        checked = []
        for workflow in ("ios-release.yml", "store-checks.yml"):
            text = (ROOT / ".github" / "workflows" / workflow).read_text()
            for match in re.finditer(r"^  ([A-Za-z0-9_-]+):\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", text.split("\njobs:\n", 1)[1],
                                     re.M | re.S):
                job, body = match.group(1), match.group(2)
                if self.ASC_INSTALL not in body:
                    continue
                checked.append((workflow, job))
                with self.subTest(workflow=workflow, job=job):
                    setup = body.find("actions/setup-python@")
                    self.assertGreater(setup, -1)
                    self.assertLess(setup, body.index("python3 scripts/store/"))
                    self.assertRegex(body, r"actions/setup-python@[0-9a-f]{40} # v\d")
                    self.assertIn('python-version: "3.13"', body)
        self.assertEqual(checked, [("ios-release.yml", "prepare"), ("ios-release.yml", "wait-for-build"),
                                   ("ios-release.yml", "app-store-connect"), ("store-checks.yml", "offline")])

    def test_every_job_that_runs_asc_installs_and_checks_the_pinned_release_first(self) -> None:
        commands = {
            "prepare": ("asc_release.py --create-version", "asc_release.py --preflight", "ios_release.py build-number"),
            "wait-for-build": ("ios_release.py wait-build",),
            "app-store-connect": ('asc_release.py "${args[@]}"',),
        }
        for job, uses in commands.items():
            body = self.job(job)
            with self.subTest(job=job):
                install = self.step(job, self.INSTALL)
                self.assertIn(self.ASC_INSTALL, install)
                self.assertIn(self.ASC_CHECK, install)
                self.assertLess(install.index(self.ASC_INSTALL), install.index(self.ASC_CHECK))
                for command in uses:
                    self.assertLess(body.index(self.ASC_INSTALL), body.index(command), command)
                # asc replaced the hand-written API client and its PyJWT dependency.
                self.assertNotIn("pip install", body)
        self.assertEqual(self.WORKFLOW.count(self.ASC_INSTALL), 3)
        # The build job never runs asc: xcodebuild exports and uploads the binary.
        self.assertNotIn("asc_cli.py", self.job("build"))
        self.assertNotIn("requirements-store", self.WORKFLOW)
        self.assertFalse((ROOT / "requirements-store.in").exists())
        self.assertFalse((ROOT / "requirements-store.txt").exists())

    def test_validation_runs_use_asc_read_only(self) -> None:
        # Validation runs only reach the prepare job, and there asc refuses every write.
        self.assertIn("ASC_READ_ONLY: ${{ github.event_name == 'workflow_dispatch' && '1' || '' }}", self.job("prepare"))
        for job in ("build", "wait-for-build", "app-store-connect", "github-release"):
            self.assertNotIn("ASC_READ_ONLY", self.job(job), job)
        for job in ("wait-for-build", "app-store-connect"):
            self.assertIn("needs.prepare.outputs.mode == 'release'", self.job(job), job)
        self.assertIn("github.event_name == 'push'", self.job("github-release"))

    def test_the_creative_switch_reaches_every_store_step(self) -> None:
        self.assertIn("creative: ${{ steps.gates.outputs.creative }}", self.job("prepare"))
        self.assertIn("UPLOAD_CREATIVE_ASSETS: ${{ needs.prepare.outputs.creative }}",
                      self.step("app-store-connect", "Listing / What's New / screenshots / creative assets / review (gated)"))
        self.assertIn("IOS_UPLOAD_CREATIVE_ASSETS: ${{ vars.IOS_UPLOAD_CREATIVE_ASSETS }}",
                      self.step("github-release", "Print iOS release switches"))
        checks = (ROOT / ".github" / "workflows" / "store-checks.yml").read_text()
        self.assertIn("IOS_UPLOAD_CREATIVE_ASSETS: ${{ vars.IOS_UPLOAD_CREATIVE_ASSETS }}", checks)

    def test_store_checks_install_and_check_the_pinned_asc(self) -> None:
        # A pull request that changes the pin proves the new release downloads and matches.
        checks = (ROOT / ".github" / "workflows" / "store-checks.yml").read_text()
        self.assertIn(self.ASC_INSTALL, checks)
        self.assertIn(self.ASC_CHECK, checks)
        self.assertEqual(checks.count("      - 'scripts/store/**'\n"), 2)
        self.assertNotIn("requirements-store", checks)
        self.assertNotIn("pip install", checks)

    def test_store_steps_run_unbuffered(self) -> None:
        for command in ("ios_release.py build-number", "ios_release.py wait-build", "asc_release.py --preflight",
                        "asc_release.py --create-version", 'asc_release.py "${args[@]}"'):
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
        for script in ("ios_release.py", "asc_release.py", "asc_cli.py", "export_listing.py", "print_gates.py",
                       "validate_catalog.py", "redact_logs.py"):
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, str(HERE / script), "--help"],
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
