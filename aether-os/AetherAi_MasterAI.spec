# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['chromadb', 'chromadb.api', 'openai', 'anthropic', 'yaml', 'dotenv', 'tiktoken', 'tiktoken_ext', 'tiktoken_ext.openai_public', 'pydantic', 'uvicorn']
hiddenimports += collect_submodules('chromadb')
hiddenimports += collect_submodules('tiktoken_ext')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('agents', 'agents'), ('ai', 'ai'), ('cli', 'cli'), ('core', 'core'), ('factory', 'factory'), ('memory', 'memory'), ('registry', 'registry'), ('skills', 'skills'), ('tools', 'tools'), ('security', 'security'), ('utils', 'utils'), ('memory\\memory_store.json', 'memory'), ('registry\\registry_store.json', 'registry')],
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
    name='AetherAi_MasterAI',
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
