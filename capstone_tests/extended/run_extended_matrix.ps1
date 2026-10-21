# Windows PowerShell. Run from the repository root (or any working directory).
# Existing whisper-server benchmarks + Docker CPU/RAM and NVIDIA GPU/VRAM snapshots.
param(
    [string]$Manifest = 'capstone_tests/fixtures/manifest_smoke.csv',
    [int]$Repeats = 5,
    [int]$Warmups = 1,
    [int]$BeamSize = 5,
    [switch]$CpuOnly,
    [switch]$GpuOnly
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $repo
if ($CpuOnly -and $GpuOnly) { throw 'Choose only one of -CpuOnly and -GpuOnly' }
if ($Repeats -lt 1 -or $Warmups -lt 0 -or $BeamSize -lt 1) { throw 'Repeats and beam size must be positive; warmups cannot be negative.' }
foreach ($name in @('make','docker','python')) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "$name is not available on PATH" }
}
$manifestPath = if ([System.IO.Path]::IsPathRooted($Manifest)) { $Manifest } else { Join-Path $repo $Manifest }
if (-not (Test-Path $manifestPath)) { throw "Missing manifest: $manifestPath" }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$session = Join-Path $repo "capstone_tests\extended\results\$stamp"
New-Item -ItemType Directory -Path $session -Force | Out-Null
Copy-Item $manifestPath (Join-Path $session 'manifest_used.csv')
python capstone_tests/env_report.py --out "capstone_tests/extended/results/$stamp/environment.json"
if ($LASTEXITCODE -ne 0) { throw 'Failed to save environment report' }
$backends = @('cpu','gpu')
if ($CpuOnly) { $backends = @('cpu') }
if ($GpuOnly) { $backends = @('gpu') }

foreach ($model in @('base','small')) {
    if (-not (Test-Path "whisper.cpp\models\ggml-$model.bin")) {
        throw "Model missing. Run: make model M=$model"
    }
    foreach ($backend in $backends) {
        $gpuFlag = if ($backend -eq 'gpu') { '1' } else { '0' }
        Write-Host "`n=== $model / $backend ===" -ForegroundColor Cyan
        & make down "GPU=$gpuFlag"
        if ($LASTEXITCODE -ne 0) { throw 'Failed stopping previous server' }
        & make whisper "GPU=$gpuFlag" "WHISPER_MODEL=ggml-$model.bin"
        if ($LASTEXITCODE -ne 0) { throw "Could not start $model/$backend" }
        $ready = $false
        for ($i=0; $i -lt 120; $i++) {
            try {
                $health = Invoke-RestMethod 'http://127.0.0.1:8080/health' -Method GET -TimeoutSec 3 -ErrorAction Stop
                if ($health.status -eq 'ok') { $ready = $true; break }
            } catch { }
            Start-Sleep -Seconds 2
        }
        if (-not $ready) {
            & docker compose -f docker-compose.yml -f docker/compose.windows.yml logs --tail=60 whisper
            throw "Whisper server never became ready: $model/$backend"
        }
        Start-Sleep -Seconds 2
        $containerOutput = & docker compose -f docker-compose.yml -f docker/compose.windows.yml ps -q whisper
        $container = ([string]($containerOutput | Select-Object -First 1)).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $container) { throw 'Could not find running Whisper container ID' }
        $folder = Join-Path $session "${model}_${backend}"
        New-Item -ItemType Directory -Force $folder | Out-Null
        $csvout = "capstone_tests/extended/results/$stamp/${model}_${backend}/${model}_${backend}_trials.csv"
        & python capstone_tests/extended/monitor_run.py --model $model --backend $backend --container $container --out-dir $folder --interval 1 -- python capstone_tests/benchmark.py --manifest $manifestPath --model $model --backend $backend --out $csvout --repeats $Repeats --warmups $Warmups --beam-size $BeamSize
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "See $folder\benchmark_stderr.log and benchmark_stdout.log"
            throw "Benchmark failed: $model/$backend"
        }
        Write-Host "Saved model measurements to $folder" -ForegroundColor Green
    }
}
Write-Host "`nGenerating plots and accuracy summaries..." -ForegroundColor Cyan
& python capstone_tests/extended/accuracy_report.py --run $session
if ($LASTEXITCODE -ne 0) { throw 'Accuracy analysis failed (install requirements if necessary)' }
& python capstone_tests/extended/plot_extended.py --run $session
if ($LASTEXITCODE -ne 0) { throw 'Plotting failed (install requirements if necessary)' }
Write-Host "`nFinished. Results: $session" -ForegroundColor Green
Write-Host 'Whisper server may remain running. Use make down to stop it.'
