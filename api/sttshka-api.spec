# Build the Python sidecar for the desktop app: `pyinstaller sttshka-api.spec`
#
# onedir, not onefile: a one-file bundle unpacks ~200 MB of native libraries to
# a temp dir on every launch, which would add seconds to an app the user opens
# all day. Models stay outside the bundle either way.
import sys  # noqa: F401  (kept: PyInstaller spec files are exec'd with it available)

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

# onnxruntime ships native libraries and transformer/tokenizer data files that
# static analysis of our imports cannot see; collect them wholesale.
for package in ("onnxruntime", "onnx_asr", "transformers", "tokenizers", "av"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# uvicorn launches via programmatic API in main.py's __main__ block.
hiddenimports += ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.lifespan.on"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "tensorflow", "PIL", "matplotlib", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sttshka-api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="sttshka-api",
)
# No BUNDLE: Electron owns the .app, this only needs to be a plain executable
# directory that gets copied into the app's Resources.
