param([switch]$NoShortcuts, [switch]$Launch)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$environment = Join-Path $root '.venv'
$python = Join-Path $environment 'Scripts\python.exe'
$pythonw = Join-Path $environment 'Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $environment
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $environment
    } else {
        throw 'Install Python 3.12 or later for Windows, including Tcl/Tk, then run setup again.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment.' }
}
& $python -c "import sys, tkinter; assert sys.version_info >= (3, 12), 'Python 3.12+ is required'"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ with Tcl/Tk is required.' }
& $python -m pip --isolated install --index-url 'https://pypi.org/simple' --only-binary=:all: -r (Join-Path $root 'requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $python -m pip --isolated install --index-url 'https://pypi.org/simple' --no-deps -e $root
if ($LASTEXITCODE -ne 0) { throw 'Application installation failed.' }
if (-not $NoShortcuts) {
    $icon = & $python -c "from golf_icon import write_ico; from golf_store import app_data_dir; print(write_ico(app_data_dir() / 'golfdesk.ico'))"
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the app icon.' }
    $icon = ([string]$icon).Trim()
    $shell = New-Object -ComObject WScript.Shell
    $arguments = '-I "' + (Join-Path $root 'golf_app.py') + '"'
    $locations = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
    foreach ($folder in $locations) {
        $path = Join-Path $folder 'Golf Desk.lnk'
        if (Test-Path -LiteralPath $path) {
            $existing = $shell.CreateShortcut($path)
            if ($existing.Description -notlike 'Local Garmin golf dashboard*' -and $existing.TargetPath -ne $pythonw) {
                Write-Warning "An unrelated shortcut was left unchanged: $path"
                continue
            }
        }
        $shortcut = $shell.CreateShortcut($path)
        $shortcut.TargetPath = $pythonw
        $shortcut.Arguments = $arguments
        $shortcut.WorkingDirectory = $root
        $shortcut.IconLocation = $icon + ',0'
        $shortcut.Description = 'Local Garmin golf dashboard with Windows-encrypted remembered sign-in'
        $shortcut.Save()
    }
}
Write-Output 'Golf Desk is ready. Open it from the desktop or Start menu.'
Write-Output 'Each person signs in with their own Garmin account. Never share session files or private exports.'
if ($Launch) {
    Start-Process -FilePath $pythonw -ArgumentList ('-I "' + (Join-Path $root 'golf_app.py') + '"') -WorkingDirectory $root
}
