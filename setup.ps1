$ErrorActionPreference = 'Stop'
$taskPython = & (Join-Path $PSScriptRoot 'start.ps1') -PythonPath
if (-not $taskPython) { throw 'Python 3.10+ not found.' }
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $taskPython -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check network and proxy settings.' }
& $venvPython (Join-Path $PSScriptRoot 'launch.py') doctor
Write-Output 'Setup complete. Run start.cmd to open Corpus Collector.'
