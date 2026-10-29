# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org).

## What is signed

Only files built from the source code in this repository by GitHub Actions
([`.github/workflows/windows-setup.yml`](../.github/workflows/windows-setup.yml)):

- the launcher `PDF-Tool.exe` (built from [`windows-app/installer/launcher`](../windows-app/installer/launcher))
- the setup `PDF-Tool-Setup-<version>.exe` (Inno Setup, built by [`windows-app/build.py`](../windows-app/build.py))

Bundled third-party open source components (the Python runtime, Qt/PySide6, LibreOffice, Tesseract and
others, listed in [THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md)) are shipped as their upstream
projects publish them and are not signed with this certificate.

## Team roles

- Committers and reviewers: members of the [Jerico3241/PDF-Tool](https://github.com/Jerico3241/PDF-Tool)
  repository with write access ([Jerico3241](https://github.com/Jerico3241)). Changes from anyone else are
  reviewed by a committer before they are merged.
- Approvers (every signing request is approved manually): [Jerico3241](https://github.com/Jerico3241).

All team members use multi-factor authentication for GitHub and SignPath.

## Privacy policy

This program will not transfer any information to other networked systems unless specifically requested
by the user or the person installing or operating it. The only connections are the update check against
the GitHub releases of this repository (can be turned off in Settings → Updates) and the optional download
of the local AI model from Hugging Face when the user asks for it. Details: [DATENSCHUTZ.md](DATENSCHUTZ.md).

## Uninstalling

Novadesk is removed via Windows Settings → Apps → Installed apps → Novadesk (PDF Tool) → Uninstall.
