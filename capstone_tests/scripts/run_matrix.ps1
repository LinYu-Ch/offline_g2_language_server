# Compatibility entry point. The maintained runner saves timestamped results.
param(
    [string]$Manifest = 'capstone_tests/fixtures/manifest_smoke.csv',
    [int]$Repeats = 5,
    [int]$Warmups = 1,
    [int]$BeamSize = 5,
    [switch]$CpuOnly,
    [switch]$GpuOnly
)
$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '..\extended\run_extended_matrix.ps1'
& $runner @PSBoundParameters
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
