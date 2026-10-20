# Security Policy

ABYSM is a single-player game with no accounts, no login, no ads, and no
server of its own. It still has a few things worth protecting: the
"Unlock the Deep" purchase, the App Store Connect credentials used by the
release pipeline, and the website. Thanks for helping keep them safe.

## Components

This policy covers:

- the iOS/iPadOS app (`Abysm/`), including its saved state (`UserDefaults`)
  and the RevenueCat/StoreKit purchase flow;
- the website and its Cloudflare Worker (`web/`), served at
  [abysm.apoorvdarshan.com](https://abysm.apoorvdarshan.com/);
- the GitHub Actions workflows and release tooling (`.github/workflows/`,
  `scripts/`, `store/`), which handle App Store Connect and signing secrets
  during release runs.

## Supported versions

| Component | Supported |
|---|---|
| iOS app — latest App Store release | ✅ |
| iOS app — older App Store releases | ❌ (please update) |
| Website and Worker — current deployment | ✅ |
| `main` branch (source) | ✅ |
| Forks and unofficial builds | ❌ |

## Reporting a vulnerability

**Do not open a public issue for a security problem.** Report it privately in
either of these ways:

- GitHub's private vulnerability reporting:
  [Report a vulnerability](https://github.com/apoorvdarshan/abysm/security/advisories/new)
- Email **[ad13dtu@gmail.com](mailto:ad13dtu@gmail.com?subject=ABYSM%20security%20report)**
  with the subject "ABYSM security report"

Please include:

1. What the problem is and what an attacker could do with it
2. Steps to reproduce (a proof of concept helps)
3. The affected component and version: app version and build, device and iOS
   version, website URL, or commit
4. Any fix you would suggest

What to expect:

- An acknowledgement within **72 hours**
- A first assessment within **7 days**
- A coordinated fix and disclosure plan once the issue is confirmed. Fixes for
  high and critical issues target 30 days, and any confirmed vulnerability of
  medium or higher severity is fixed within 60 days of being reported.

## In scope

- Getting "Unlock the Deep" in an official App Store build without a valid
  purchase or restore (for example, by tampering with entitlement handling)
- Leaking App Store Connect key IDs, issuer IDs, private keys, or signing
  identities through workflow logs, artifacts, or release tooling
- Workflow injection or privilege escalation in `.github/workflows/`
- Crashes or data loss caused by malformed saved state that a normal user could
  trigger
- Vulnerable dependencies that affect the app, the website, or the release
  tooling
- Website or Worker issues such as content injection or header misconfiguration

## Out of scope

- Building ABYSM yourself from this source. The code is MIT-licensed, so a
  personal build that does not include the paywall is allowed, not a
  vulnerability. Only official App Store builds are in scope for purchase
  bypasses.
- Modifying local data on a jailbroken device
- Problems in Apple's, RevenueCat's, GitHub's, or Cloudflare's own services
  (please report those to the vendor)
- Denial of service, spam, or social engineering

## How the project stays secure

- Secrets live only in GitHub Actions secrets. Release jobs run only for
  `v<MARKETING_VERSION>` tags, every store switch is off unless set, and build
  logs are redacted before they are kept as artifacts
  (`scripts/store/redact_logs.py`). If redaction fails, nothing is uploaded.
- Every GitHub Action is pinned to a full commit SHA. The App Store Connect
  CLI (`asc`) that the release jobs run is pinned to one release and installed
  only when its SHA-256 matches. The store tooling (Pillow) and the fuzzer are
  installed only from hash-locked requirements.
- Dependabot keeps dependencies current and opens security updates. Secret
  scanning and push protection are enabled.
- CodeQL scans Swift, Python, JavaScript, and the workflows. OpenSSF Scorecard
  runs weekly and on every push to `main`.
- The release tooling's security-relevant parsing (log redaction, release
  switches, release notes) is fuzzed with Atheris (`fuzz/`).

## Solo-maintainer workflow

ABYSM is maintained by Apoorv Darshan alone. The `Protect main` ruleset blocks
force pushes to `main` and deletion of `main`. Changes may land through pull
requests or direct pushes, and no second person's approval is required, because
there is no second maintainer to give it.

Scorecard's `Code-Review` and `Branch-Protection` recommendations for
independent reviewers are accepted exceptions for this solo project, and their
alerts are dismissed with that reason. They do not excuse dependency
vulnerabilities or problems in the code, which are fixed. These exceptions will
be revisited if the project gains another maintainer.

## Disclosure

Once a fix is in the App Store, on the website, or on `main` (whichever is
affected), the maintainer will:

- publish a GitHub Security Advisory for the issue and request a CVE when one
  applies;
- credit the reporter, with their permission;
- note the fix in the release notes.
