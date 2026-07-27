# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


datas = [("backend/static", "backend/static")] + collect_data_files("playwright")
hiddenimports = collect_submodules("playwright") + ["backend.sources.jphoo"]

a = Analysis(
    ["yav_v2.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Yav-V2",
    console=False,
    debug=False,
    upx=True,
)