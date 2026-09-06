# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('certs', 'certs'), ('assets', 'assets'), ('assets_ios', 'assets_ios'), ('shopicons', 'shopicons'), ('site', 'site'), ('game_master.bin', '.')]
binaries = []
hiddenimports = ['places', 'admin', 'events', 'world', 'settings', 'gamedata', 'shop',
                 'helpcenter', 'dupe_test',   # dupe_test is imported lazily by protocol.py
                 'biomes', 'leveling', 'pois',  # all lazily imported by protocol.py too
                 'sso_bridge', 'windstock_site',   # imported inside run.main(); 0.35's plain-HTTP login door
                 'poidownload', 'downloads_ui',   # World Manager: country/state POI downloads
                 'fetch_pois_pbf', 'fetch_osm_pois']  # osmium PBF parse, lazily imported by poidownload
tmp_ret = collect_all('s2sphere')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# osmium is a native extension used to parse OpenStreetMap .pbf extracts for the
# World Manager's World Data page. Bundle its binaries + data so downloads work
# from the packaged exe, not just from source.
tmp_ret = collect_all('osmium')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Start-Pokemon-GO-Server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
