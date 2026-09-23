"""Baut payload.zip und die Windows-Setup.exe."""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path("/workspace/windows-app")
RUNTIME = Path("/tmp/winpkg/runtime_full")
PAYLOAD_DIR = Path("/tmp/winpkg/payload")
INSTALLER = ROOT / "installer"
OUT_DIR = Path("/workspace/public/downloads")
ARTIFACTS = Path("/workspace/artifacts")
GO = Path("/tmp/winpkg/go/bin/go")
SETUP_NAME = "Uebersichten-Ersteller-Setup.exe"
ZIP_NAME = "Uebersichten-Ersteller-Windows.zip"


def copytree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def zip_dir(src: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in src.rglob("*"):
            if path.is_file():
                if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                    continue
                z.write(path, path.relative_to(src).as_posix())


def write_start_vbs(dest: Path) -> None:
    dest.write_text(
        "Set fso = CreateObject(\"Scripting.FileSystemObject\")\n"
        "root = fso.GetParentFolderName(WScript.ScriptFullName)\n"
        "py = root & \"\\runtime\\pythonw.exe\"\n"
        "app = root & \"\\app\\start.py\"\n"
        "If Not fso.FileExists(py) Then\n"
        "  MsgBox \"Die Laufzeit fehlt. Bitte Uebersichten-Ersteller-Setup.exe verwenden.\", 16, \"Uebersichten-Ersteller\"\n"
        "  WScript.Quit 1\n"
        "End If\n"
        "Set sh = CreateObject(\"WScript.Shell\")\n"
        "sh.CurrentDirectory = root & \"\\app\"\n"
        "sh.Run \"\"\"\" & py & \"\"\" \"\"\" & app & \"\"\"\", 0, False\n",
        encoding="utf-8",
    )


def main() -> None:
    if not (RUNTIME / "pythonw.exe").exists():
        raise SystemExit(f"Runtime fehlt: {RUNTIME}")
    if not (RUNTIME / "DLLs" / "_tkinter.pyd").exists():
        raise SystemExit("tkinter fehlt in der Runtime")

    if PAYLOAD_DIR.exists():
        shutil.rmtree(PAYLOAD_DIR)
    PAYLOAD_DIR.mkdir(parents=True)

    copytree(RUNTIME, PAYLOAD_DIR / "runtime")
    copytree(ROOT / "app", PAYLOAD_DIR / "app")
    copytree(ROOT / "assets", PAYLOAD_DIR / "assets")
    shutil.copy2(ROOT / "README.txt", PAYLOAD_DIR / "README.txt")
    write_start_vbs(PAYLOAD_DIR / "Start.vbs")

    payload_zip = INSTALLER / "payload.zip"
    print("zip payload …")
    zip_dir(PAYLOAD_DIR, payload_zip)
    print("payload", payload_zip.stat().st_size)

    env = os.environ.copy()
    env["PATH"] = str(GO.parent) + os.pathsep + env.get("PATH", "")
    env["GOROOT"] = str(GO.parent.parent)
    env["GOPATH"] = "/tmp/winpkg/gopath"
    env["GOCACHE"] = "/tmp/winpkg/gocache"
    env["GOMODCACHE"] = "/tmp/winpkg/gomodcache"
    env["CGO_ENABLED"] = "0"
    env["GOOS"] = "windows"
    env["GOARCH"] = "amd64"

    if not (INSTALLER / "go.mod").exists():
        subprocess.check_call([str(GO), "mod", "init", "uebersichtenersteller"], cwd=INSTALLER, env=env)
    subprocess.check_call([str(GO), "get", "golang.org/x/sys@v0.34.0"], cwd=INSTALLER, env=env)
    subprocess.check_call([str(GO), "mod", "tidy"], cwd=INSTALLER, env=env)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_dir = ARTIFACTS
    try:
        artifact_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        artifact_dir = ROOT / "dist"
        artifact_dir.mkdir(parents=True, exist_ok=True)
    exe_path = OUT_DIR / SETUP_NAME
    print("go build …")
    subprocess.check_call(
        [
            str(GO),
            "build",
            "-trimpath",
            "-ldflags",
            "-H windowsgui -s -w",
            "-o",
            str(exe_path),
            ".",
        ],
        cwd=INSTALLER,
        env=env,
    )
    shutil.copy2(exe_path, artifact_dir / SETUP_NAME)
    print("exe", exe_path.stat().st_size)

    portable = OUT_DIR / ZIP_NAME
    print("zip portable …")
    zip_dir(PAYLOAD_DIR, portable)
    shutil.copy2(portable, artifact_dir / ZIP_NAME)
    shutil.copy2(ROOT / "README.txt", OUT_DIR / "README.txt")
    shutil.copy2(ROOT / "README.txt", artifact_dir / "README.txt")
    for stale in (
        "VertraView-Setup.exe",
        "VertraView-Windows.zip",
        "VertraView-Source.zip",
        "VertraView-Komplett.zip",
        "Vertragsuebersicht-Setup.exe",
        "Vertragsuebersicht-Windows.zip",
    ):
        for folder in (OUT_DIR, artifact_dir):
            p = folder / stale
            if p.exists():
                p.unlink()
    print("portable", portable.stat().st_size)
    print("OK")


if __name__ == "__main__":
    main()
