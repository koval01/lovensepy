# -*- mode: python ; coding: utf-8 -*-
#
# Windows PyInstaller spec for bundling the LovensePy service as a single executable.
#
# Build (local dev on Windows):
#   pyinstaller --clean --noconfirm lovensepy-service-win.spec

import glob
import os

from PyInstaller.utils.hooks import collect_submodules


block_cipher = None

def _collect_ble_branding_data() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for p in glob.glob("lovensepy/ble_direct/toy_config_ble_marketing*.json"):
        out.append((p, "lovensepy/ble_direct"))
    return out


datas = _collect_ble_branding_data()
if os.path.exists("pyproject.toml"):
    # Used by lovensepy._http_identity.package_version() fallback in PyInstaller bundles
    # where importlib.metadata may not find dist-info.
    datas.append(("pyproject.toml", "."))

# Be defensive about dynamic imports.
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
    binaries=[],
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
)

