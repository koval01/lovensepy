from __future__ import annotations

import glob
import importlib.util
import os
import shlex
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> None:
    print("+", " ".join(shlex.quote(c) for c in cmd), flush=True)
    subprocess.check_call(cmd)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    # Data files required at runtime.
    data_args: list[str] = []
    if (root / "pyproject.toml").is_file():
        data_args += ["--include-data-file=pyproject.toml=pyproject.toml"]

    for p in glob.glob("lovensepy/ble_direct/toy_config_ble_marketing*.json"):
        rel = p.replace("\\", "/")
        dst = rel  # keep same relative path inside the bundle
        data_args += [f"--include-data-file={rel}={dst}"]

    is_macos = sys.platform == "darwin"

    # uvloop is not shipped / not supported on Windows; uvicorn[standard] skips it there too.
    uvicorn_extra_pkgs: list[str] = [
        "--include-package=websockets",
        "--include-package=watchfiles",
        "--include-package=httptools",
    ]
    if importlib.util.find_spec("uvloop") is not None:
        uvicorn_extra_pkgs.insert(0, "--include-package=uvloop")

    # Onefile produces a single executable; it extracts to a temp dir at runtime (like yt-dlp).
    # On macOS, PyObjC modules (pulled in by bleak/CoreBluetooth) require "app" mode in Nuitka.
    # Nuitka default output base name is derived from the main module; keep it stable.
    if is_macos:
        out_dir = "dist-nuitka"
        out_base = "lovensepy-service"
    else:
        out_dir = "dist-nuitka"
        out_base = "lovensepy-service"

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--mode=app" if is_macos else "--mode=onefile",
        "--follow-imports",
        "--follow-stdlib",
        "--assume-yes-for-downloads",
        "--output-filename=" + out_base,
        "--output-dir=" + out_dir,
        "--include-package=lovensepy",
        "--nofollow-import-to=lovensepy.services.fastapi",
        # Dev/test-only aiohttp and uvloop edges pull unittest and slow Nuitka a lot.
        "--nofollow-import-to=aiohttp.test_utils",
        "--nofollow-import-to=uvloop._testbase",
        # Force-include FastAPI stack; Nuitka otherwise may generate incomplete stubs.
        "--include-package=fastapi",
        "--include-package=starlette",
        "--include-package=uvicorn",
        "--include-module=fastapi.applications",
        "--include-module=fastapi.routing",
        "--include-module=fastapi.params",
        "--include-module=starlette.applications",
        # Optional deps (present via extras in CI):
        "--include-package=aiohttp",
        "--include-package=pydantic",
        *uvicorn_extra_pkgs,
        "--include-package=yaml",
        *data_args,
        "lovensepy/services/launcher.py",
    ]
    _run(cmd)


if __name__ == "__main__":
    main()
