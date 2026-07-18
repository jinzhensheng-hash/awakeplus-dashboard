$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = "C:\Users\kjs66\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $Python)) {
  throw "Codex bundled Python was not found: $Python"
}

& $Python "$PSScriptRoot\awakeplus_collect.py" --root $Root --latest-count 1
