$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$orbitaPythonCandidates = @($env:ORBITA_PYTHON, (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'), (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
$orbitaPython = $orbitaPythonCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $orbitaPython) { $orbitaPython = (Get-Command python -ErrorAction Stop).Source }
& $orbitaPython (Join-Path $PSScriptRoot 'build_desktop.py')
if ($LASTEXITCODE -ne 0) { throw 'Orbita build failed' }
