# Installs the Python packages, puts an "Ekrovi" shortcut on the desktop and starts it.
#   .\install.ps1            install
#   .\install.ps1 -Startup   also start Ekrovi when Windows starts
param([switch]$Startup)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$exe = & python -c "import sys; print(sys.executable)"
if (-not $exe) { throw 'Python 3.10+ not found. Install it from python.org and run this again.' }
$pyw = Join-Path (Split-Path $exe) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $exe }

& $exe -m pip install --user --quiet -r (Join-Path $here 'requirements.txt')

function New-Shortcut($folder) {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path $folder 'Ekrovi.lnk'))
    $lnk.TargetPath = $pyw
    $lnk.Arguments = '"' + (Join-Path $here 'ekrovi.pyw') + '"'
    $lnk.WorkingDirectory = $here
    $lnk.IconLocation = Join-Path $here 'ekrovi.ico'
    $lnk.Description = 'PrtScr sends your screen to Claude'
    $lnk.Save()
}

New-Shortcut ([Environment]::GetFolderPath('Desktop'))
if ($Startup) { New-Shortcut ([Environment]::GetFolderPath('Startup')) }

Start-Process -FilePath $pyw -ArgumentList ('"' + (Join-Path $here 'ekrovi.pyw') + '"') -WorkingDirectory $here
Write-Host 'Ekrovi is running. Press PrtScr with the Claude desktop app open.'
