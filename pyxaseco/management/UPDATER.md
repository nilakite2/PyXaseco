# File Updates

## In Game

All update controls require MasterAdmin access.

| Command | Action |
| --- | --- |
| `//apps updates` | Verify both publishers and list available packages. |
| `//apps download controller` | Download and verify the controller ZIP. |
| `//apps update controller` | Review file changes. |
| `//apps update controller confirm` | Back up and copy; keep modified code. |
| `//apps update controller force` | Review with Force Replace selected. |
| `//apps update controller force confirm` | Also replace modified official code after backup. |
| `//pyres` | Load copied files through the existing controller restart. |

Use an app ID instead of controller for an optional app. Review and confirmation
are also available as window buttons. Downloading does not install or enable it;
installing a new app adds a disabled loadout entry. Enable it separately.

Existing TOML settings and .env are not overwritten. Every app_defaults.toml is
backed up first. Incoming configuration templates, original modified files,
readable diffs and the operation report are saved beneath
.management-maintenance/file-updates/. Unknown custom files remain untouched.
Only files known to an official inventory are considered for obsolete deletion.

The owner receives a private completion notice to run //pyres. No automatic
restart, Python installation, library installation or environment switching.
Dependency declarations are checked against the existing installation; missing
requirements require explicit owner action. File rollback does not change a DB.

## Enable Validation

In apps/apps_manager/app_defaults.toml, configure apps_manager.updates:

```toml
enabled = true
channel = "development"
github_manifest = "https://github.com/nilakite2/PyXaseco/releases/download/v1.5-validation/catalogue.json"
validation_manifest = "https://tmtrialgy.com/api/pyxaseco/updates/development.json"
public_key = "<locally supplied public-key.txt contents>"
check_interval_seconds = 3600
notice_interval_seconds = 1800
```

Use the actual GitHub release tag. Do not enable until both hosts are published.
Manual commands reread settings; restart after configuring to enable periodic
checks. Automatic checks/notices are owner-only and do not install anything.
Keep the private signing key outside source trees and publication folders.

## Publish

From the controller source folder, using the existing Python:

```powershell
python -m pyxaseco.management.publish_release keygen --key "D:\Private\pyxaseco-signing.pem"
python -m pyxaseco.management.publish_release build --source "." --baseline "D:\PublishedClean\PyXaseco" --baseline-version 1.4 --version 1.5 --key "D:\Private\pyxaseco-signing.pem" --output "D:\ReleaseOutput\pyxaseco-releases" --channel development --github-base "https://github.com/nilakite2/PyXaseco/releases/download/v1.5-validation"
```

Replace example paths. The baseline must be the actual clean published release,
not a customized live server. For a new app absent there, its baseline is empty.
Add `--package quotes` (or another public app ID) to publish an app separately.
The controller ZIP excludes independently managed optional apps. Only build from
a clean distribution checkout: never ship live credentials in app defaults.
Review required libraries/app compatibility for each release; this builder does
not infer arbitrary app dependencies from Python imports. Exact pinned libraries
are read from the controller requirements.txt; optional-app packages can declare
them with repeated --library name==version options. Missing/mismatched libraries
are shown in Review and block copying until the owner installs them explicitly
with the existing Python. No wheels, pip commands or new environments are run.
The working controller reports 1.5. Keep validation packages on the development
channel until in-game testing is complete; the published baseline remains 1.4.

Copy the generated publication folder to the website as described in its
PYXASECO_UPDATES.md. Upload the matching ZIPs and exact channel/catalogue.json
as GitHub release assets. Each regenerated catalogue increments its sequence;
publish the regenerated file on both hosts. Changed ZIPs require a new version.
Approvals expire after 30 days; rebuild the same unchanged package to renew.

The publisher signs exact catalogue bytes with Ed25519. This is separate from
Windows executable signing. Clients trust a public key configured locally, not
one supplied by a remote catalogue. If either host is unavailable, disagrees,
serves an expired signature, or returns altered files, updating is postponed;
normal gameplay continues.

## Local CLI

```powershell
python -m pyxaseco.management.update_client --controller-version 1.4 check
python -m pyxaseco.management.update_client --controller-version 1.4 stage controller
python -m pyxaseco.management.update_client --controller-version 1.4 review controller
python -m pyxaseco.management.update_client --controller-version 1.4 apply controller --confirm
```

Use the actual installed version. Optional `--force` replaces modified code;
`--review HASH` binds copying to a previously reviewed file snapshot.
If a copy is interrupted, keep its backups/report and active.json guard for
recovery; do not delete the guard blindly or restart into partially copied code.
