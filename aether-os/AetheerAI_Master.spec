# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['streamlit', 'chromadb', 'chromadb.api', 'openai', 'anthropic', 'yaml', 'dotenv', 'tiktoken', 'tiktoken_ext', 'tiktoken_ext.openai_public', 'pydantic', 'uvicorn', 'requests', 'bs4', 'pandas', 'PIL', 'cryptography', 'threading', 'concurrent.futures']
hiddenimports += collect_submodules('chromadb')
hiddenimports += collect_submodules('tiktoken_ext')
hiddenimports += collect_submodules('streamlit')


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\Tecbunny Solutions\\AppData\\Local\\Programs\\Python\\Python310\\lib\\site-packages\\streamlit\\static', 'streamlit\\static'), ('C:\\Users\\Tecbunny Solutions\\AppData\\Local\\Programs\\Python\\Python310\\lib\\site-packages\\streamlit\\runtime', 'streamlit\\runtime'), ('C:\\Users\\Tecbunny Solutions\\AppData\\Local\\Programs\\Python\\Python310\\lib\\site-packages\\streamlit\\components', 'streamlit\\components'), ('app.py', '.'), ('agents', 'agents'), ('ai', 'ai'), ('cli', 'cli'), ('core', 'core'), ('factory', 'factory'), ('memory', 'memory'), ('registry', 'registry'), ('security', 'security'), ('skills', 'skills'), ('tools', 'tools'), ('utils', 'utils'), ('workspace', 'workspace'), ('agent_output', 'agent_output'), ('memory\\memory_store.json', 'memory'), ('registry\\registry_store.json', 'registry')],
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
    name='AetheerAI_Master',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
