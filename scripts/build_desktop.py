#!/usr/bin/env python3
"""Build the Windows application, offline installer and checked distribution archive."""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/desktop"
OUTPUT = ROOT / "dist/desktop"
VERSION = runpy.run_path(str(ROOT / "backend/src/kroika_backend/desktop_version.py"))["VERSION"]


def icon(path: Path) -> None:
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (256, 256))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 255, 255), radius=54, fill="#193C40")
    points = [(86, 39), (107, 60), (149, 60), (170, 39), (210, 83), (184, 111),
              (168, 101), (176, 211), (80, 211), (88, 101), (72, 111), (46, 83)]
    draw.polygon(points, fill="#F5EBD7")
    draw.line([(128, 61), (128, 211)], fill="#D16441", width=5)
    for x in range(89, 168, 15):
        draw.line([(x, 139), (x + 7, 139)], fill="#193C40", width=4)
    draw.ellipse((113, 125, 143, 155), fill="#D16441")
    draw.ellipse((122, 134, 134, 146), fill="#F5EBD7")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def version_resource(path: Path) -> None:
    numbers = tuple(map(int, VERSION.split("."))) + (0,)
    path.write_text(f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0,
                   OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Kroika'), StringStruct('FileDescription', 'Кройка'),
    StringStruct('FileVersion', '{VERSION}'), StringStruct('ProductVersion', '{VERSION}'),
    StringStruct('ProductName', 'Кройка'), StringStruct('OriginalFilename', 'Kroika.exe')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])
''', encoding="utf-8")


def inventory() -> None:
    target = WORK / "THIRD_PARTY"
    target.mkdir(parents=True, exist_ok=True)
    dependencies = []
    for distribution in sorted(metadata.distributions(), key=lambda item: item.metadata["Name"].lower()):
        name = distribution.metadata["Name"]
        dependencies.append({"name": name, "version": distribution.version})
        for file in distribution.files or []:
            lowered = str(file).lower()
            if any(token in lowered for token in ("license", "copying", "notice")) and not lowered.endswith((".py", ".pyc")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    destination = target / name / str(file).replace("..", "_")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    (target / "INVENTORY.json").write_text(json.dumps(dependencies, indent=2), encoding="utf-8")


def verify_microsoft_installer(path: Path) -> None:
    if not path.is_file():
        raise ValueError("Укажите полный offline-установщик WebView2 x64.")
    powershell = shutil.which("pwsh.exe") or "powershell.exe"
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(ROOT / "packaging/windows/verify-runtime.ps1"),
                             "-RuntimeInstaller", str(path.resolve())],
                            capture_output=True, check=False)
    if result.returncode:
        details = result.stderr.decode("utf-8", errors="replace")[-1500:]
        raise ValueError(f"WebView2: действительная подпись Microsoft не подтверждена. {details}")


def checksums(files: list[Path], output: Path) -> None:
    lines = []
    for file in files:
        with file.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        lines.append(f"{digest}  {file.name}\n")
    output.write_text("".join(lines), encoding="ascii")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONUTF8", "1")
    parser = argparse.ArgumentParser(description="Сборка Кройки Windows x64")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-installer", action="store_true")
    parser.add_argument("--webview2-installer", type=Path)
    parser.add_argument("--iscc", type=Path)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("Windows exe нужно собирать на Windows x64.")
    if not args.skip_installer:
        if args.webview2_installer is None:
            parser.error("Нужен --webview2-installer с offline-установщиком Microsoft x64.")
        verify_microsoft_installer(args.webview2_installer)
    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    icon(WORK / "kroika.ico")
    version_resource(WORK / "version.txt")
    inventory()
    if not args.skip_frontend:
        npm = shutil.which("npm.cmd")
        if not npm:
            parser.error("Для сборки интерфейса нужен Node.js; для запуска готового exe он не требуется.")
        subprocess.run([npm, "ci"], cwd=ROOT / "frontend", check=True)
        subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    if not (ROOT / "frontend/dist/index.html").is_file():
        parser.error("Не найдена production-сборка интерфейса.")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
                    "--distpath", str(OUTPUT), "--workpath", str(WORK / "pyinstaller"),
                    str(ROOT / "packaging/windows/kroika.spec")], cwd=ROOT, check=True)
    archive = OUTPUT / f"Kroika-{VERSION}-windows-x64-portable.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for file in sorted((OUTPUT / "Kroika").rglob("*")):
            if file.is_file():
                zipped.write(file, file.relative_to(OUTPUT))
    artifacts = [archive]
    if not args.skip_installer:
        compiler = args.iscc or shutil.which("ISCC.exe") or Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6/ISCC.exe"
        subprocess.run([str(compiler), f"/DAppVersion={VERSION}", f"/DBundleDir={OUTPUT / 'Kroika'}",
                        f"/DOutputDir={OUTPUT}", f"/DRuntimeInstaller={args.webview2_installer.resolve()}",
                        f"/DAppIcon={WORK / 'kroika.ico'}", str(ROOT / "packaging/windows/installer.iss")], check=True)
        artifacts.append(OUTPUT / f"Kroika-{VERSION}-windows-x64-setup.exe")
    checksums(artifacts, OUTPUT / "SHA256SUMS.txt")
    print(f"Готово: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
