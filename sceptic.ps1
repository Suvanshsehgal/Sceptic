$venvPy = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
$cliScript = Join-Path $PSScriptRoot "cli\main.py"

if (Test-Path $venvPy) {
    & $venvPy $cliScript @args
} else {
    python $cliScript @args
}
