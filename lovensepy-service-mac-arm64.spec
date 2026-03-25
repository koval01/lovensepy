# -*- mode: python ; coding: utf-8 -*-
#
# macOS PyInstaller spec (thin build) for local testing on arm64.
#
import glob
import os
import sys
import sysconfig

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# PyInstaller should normally bundle the Python shared library automatically,
# but with our current packaging it ends up missing in `dist/_internal/`.
# Force-including it fixes runtime: "Failed to load Python shared library".
_ldlibrary = sysconfig.get_config_var("LDLIBRARY")
_libdir = sysconfig.get_config_var("LIBDIR")
_python_dylib = os.path.join(_libdir, _ldlibrary) if _ldlibrary and _libdir else None
# Put it where the bootloader expects it: `_internal/`.
_extra_binaries = (
    [(_python_dylib, "_internal")] if _python_dylib and os.path.exists(_python_dylib) else []
)

def _collect_ble_branding_data() -> list[tuple[str, str]]:
    # Explicit paths: avoid PyInstaller module-name resolution issues.
    # Pack them into `lovensepy/ble_direct/` inside the bundle.
    out: list[tuple[str, str]] = []
    for p in glob.glob("lovensepy/ble_direct/toy_config_ble_marketing*.json"):
        out.append((p, "lovensepy/ble_direct"))
    return out


datas = _collect_ble_branding_data()
if os.path.exists("pyproject.toml"):
    # Used by lovensepy._http_identity.package_version() fallback in PyInstaller bundles
    # where importlib.metadata may not find dist-info.
    datas.append(("pyproject.toml", "."))

hiddenimports = []
hiddenimports += collect_submodules("fastapi")
hiddenimports += collect_submodules("uvicorn")

try:
    hiddenimports += collect_submodules("bleak")
except Exception:
    pass
try:
    hiddenimports += collect_submodules("pick")
except Exception:
    pass

a = Analysis(
    ["lovensepy/services/launcher.py"],
    pathex=["."],
    binaries=_extra_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="lovensepy-service",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    target_arch="arm64",
)

