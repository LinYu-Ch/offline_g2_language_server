# Needs: `make whisper WHISPER_MODEL=ggml-base.bin` started beforehand.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $repo
$sample = 'whisper.cpp/bindings/go/samples/jfk.wav'
if (-not (Test-Path $sample)) { throw "JFK test WAV not found: $sample" }
Write-Host "Sending JFK WAV file to http://127.0.0.1:8080/inference ..."
& curl.exe -f -sS -F "file=@$sample" -F 'language=en' -F 'translate=false' -F 'response_format=json' 'http://127.0.0.1:8080/inference'
if ($LASTEXITCODE -ne 0) { throw 'Smoke test failed: make sure the whisper server is running. Check make logs S=whisper' }
Write-Host "`nSmoke test HTTP request completed. Check that JSON contains recognizable JFK text."
