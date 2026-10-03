param([switch]$Check, [switch]$PythonPath)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = $null
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try { $candidate = & $pyLauncher.Source -3 -c 'import sys; print(sys.executable)' 2>$null }
        catch { $candidate = $null }
        if ($LASTEXITCODE -eq 0 -and $candidate) { $taskPython = $candidate.Trim() }
    }
    if (-not $taskPython) {
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($pythonCommand) { $taskPython = $pythonCommand.Source }
    }
}
if (-not $taskPython) { throw 'Python was not found. Install Python 3.10+ with Tkinter.' }
& $taskPython -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ is required.' }
if ($PythonPath) { Write-Output $taskPython; return }
Push-Location -LiteralPath $PSScriptRoot
try {
    if ($Check) { & $taskPython -m corpus_tools doctor }
    else { & $taskPython -m corpus_tools gui }
    $taskExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $taskExitCode
