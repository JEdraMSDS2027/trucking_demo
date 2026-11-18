$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '..\..\work\demo-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (Test-Path -LiteralPath $bundledPython) {
            $basePython = $bundledPython
        } elseif (Get-Command py -ErrorAction SilentlyContinue) {
            $basePython = 'py'
        } else {
            $basePython = 'python'
        }
        New-Item -ItemType Directory -Force -Path '.runtime-tmp' | Out-Null
        $env:TEMP = (Resolve-Path -LiteralPath '.runtime-tmp').Path
        $env:TMP = $env:TEMP
        & $basePython -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create a Python environment. Install Python 3.11 or newer.' }
        & $pythonPath -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the internet connection.' }
    }
}
Write-Host 'Open http://127.0.0.1:8501 in your browser. Press Ctrl+C here to stop.'
& $pythonPath -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
