"""'Atirat' parancsikon létrehozása az Asztalon és a Start menüben (konzolablak nélküli indítás)."""

import os
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
NAME = "Atirat"

PS = r"""
$sh = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = $sh.CreateShortcut((Join-Path $dir ($env:GT_NAME + '.lnk')))
    $lnk.TargetPath = $env:GT_TARGET
    $lnk.Arguments = '"' + $env:GT_SCRIPT + '"'
    $lnk.WorkingDirectory = $env:GT_BASE
    $lnk.IconLocation = $env:GT_ICON + ',0'
    $lnk.Description = 'Google Fordító átiratok importálása a telefonról'
    $lnk.Save()
    Write-Output $lnk.FullName
}
"""

env = dict(
    os.environ,
    GT_NAME=NAME,
    GT_TARGET=str(BASE / ".venv" / "Scripts" / "pythonw.exe"),
    GT_SCRIPT=str(BASE / "gt_gui.py"),
    GT_BASE=str(BASE),
    GT_ICON=str(BASE / "atirat.ico"),
)
out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", PS], env=env,
                     capture_output=True, text=True, encoding="utf-8", errors="replace")
print(out.stdout.strip() or out.stderr.strip())
