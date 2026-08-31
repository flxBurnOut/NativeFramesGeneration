param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $HarnessArguments
)

$ErrorActionPreference = 'Stop'
$selectedPython = $env:SPRITE_PIPELINE_PYTHON

if (-not $selectedPython) {
    $localVenv = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $localVenv) {
        $selectedPython = $localVenv
    }
}

if (-not $selectedPython) {
    $pathPython = Get-Command python -ErrorAction SilentlyContinue
    if ($pathPython) {
        $selectedPython = $pathPython.Source
    }
}

if (-not $selectedPython) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundledPython) {
        $selectedPython = $bundledPython
    }
}

if (-not $selectedPython) {
    throw 'Python 3.11+ was not found. Create .venv or set SPRITE_PIPELINE_PYTHON.'
}

& $selectedPython (Join-Path $PSScriptRoot 'cli.py') @HarnessArguments
exit $LASTEXITCODE

