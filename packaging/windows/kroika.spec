from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parents[1]
datas = [(str(root / "schemas"), "kroika_resources/schemas"),
         (str(root / "frontend/dist"), "kroika_resources/frontend/dist"),
         (str(root / "build/desktop/kroika.ico"), "kroika_resources"),
         (str(root / "LICENSES"), "kroika_resources/LICENSES"),
         (str(root / "build/desktop/THIRD_PARTY"), "kroika_resources/THIRD_PARTY"),
         (str(root / "examples/v1/example-dress-project.json"), "kroika_resources/examples/v1"),
         (str(root / "examples/v1/example-engine-request.json"), "kroika_resources/examples/v1"),
         (str(root / "examples/v1/example-ai-request.json"), "kroika_resources/examples/v1"),
         (str(root / "examples/v1/example-ai-response.json"), "kroika_resources/examples/v1"),
         (str(root / "packaging/test_resources"), "kroika_resources/packaging/test_resources"),
         (str(root / "evaluation/stage10/images/synthetic-02.png"), "kroika_resources/evaluation/stage10/images"),
         (str(root / "evaluation/stage10/images/synthetic-01.png"), "kroika_resources/evaluation/stage10/images")]
for package in ("kroika_contracts", "webview", "certifi", "reportlab"):
    datas += collect_data_files(package)
for package in ("kroika-contracts", "kroika-pattern-engine", "kroika-backend", "pywebview", "keyring", "pythonnet"):
    datas += copy_metadata(package)
hidden = []
for package in ("kroika_backend", "kroika_contracts", "kroika_pattern_engine", "uvicorn"):
    hidden += collect_submodules(package)
hidden += ["webview", "webview.platforms.winforms", "webview.platforms.edgechromium",
           "keyring.backends.Windows", "clr", "pythonnet", "socksio"]
a = Analysis([str(root / "packaging/desktop_entry.py")],
             pathex=[str(root / "src"), str(root / "backend/src"), str(root / "pattern-engine/src")],
             binaries=[], datas=datas, hiddenimports=hidden,
             excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter", "pytest", "IPython"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Kroika", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(root / "build/desktop/kroika.ico"),
          version=str(root / "build/desktop/version.txt"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Kroika")
