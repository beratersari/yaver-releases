# -*- mode: python ; coding: utf-8 -*-
"""Onedir freeze of the office release site.

The zip is built by packaging/pyinstaller/build.py. Its root is the
executable, _internal, .env.example, START_HERE.txt, and VERSION.
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPECDIR = Path(SPECPATH)
ROOT = SPECDIR.parent.parent

datas = [
    (str(ROOT / "yaver_releases" / "templates"), "yaver_releases/templates"),
    (str(ROOT / "yaver_releases" / "static"), "yaver_releases/static"),
    (str(ROOT / "yaver_releases" / "update_scripts"), "yaver_releases/update_scripts"),
    (str(ROOT / ".env.example"), "."),
]
binaries: list = []
hiddenimports: list = list(collect_submodules("yaver_releases"))

_COLLECT_PACKAGES = (
    "fastapi",
    "starlette",
    "uvicorn",
    "pydantic",
    "pydantic_core",
    "jinja2",
    "markupsafe",
    "anyio",
    "httpx",
    "httpcore",
    "h11",
    "idna",
    "certifi",
    "sniffio",
    "click",
    "multipart",
    "python_multipart",
    "httptools",
    "websockets",
    "watchfiles",
    "annotated_types",
    "typing_extensions",
)

for pkg in _COLLECT_PACKAGES:
    try:
        collected_datas, collected_binaries, collected_hidden = collect_all(pkg)
    except Exception:
        hiddenimports.append(pkg)
        continue
    datas += collected_datas
    binaries += collected_binaries
    hiddenimports += collected_hidden

hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

excludes = [
    "pytest",
    "IPython",
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "PIL",
    "notebook",
]

a = Analysis(
    [str(SPECDIR / "entrypoint.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(SPECDIR / "runtime_hook.py")],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="yaver-releases",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
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
    upx_exclude=[],
    name="yaver-releases",
)
