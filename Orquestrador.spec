# PyInstaller is executed on Windows; one distributed GUI executable, no separate installer.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = [("scripts", "scripts"), ("payload-manifest.json", ".")]
for package in ("PySide6", "selenium", "pandas", "requests", "openpyxl", "psutil"):
    datas += copy_metadata(package)
datas += collect_data_files("selenium")
hidden = ["pipefy_orchestrator", "automation_schedule", "win32com.client", "pythoncom", "pywintypes"]
for package in ("selenium", "openpyxl", "psutil"):
    hidden += collect_submodules(package)
a = Analysis(["desktop_entry.py"], pathex=["."], binaries=[], datas=datas,
             hiddenimports=hidden, hookspath=[], runtime_hooks=[], excludes=["tkinter"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="Orquestrador", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False, target_arch=None, codesign_identity=None,
          entitlements_file=None, uac_admin=False)
