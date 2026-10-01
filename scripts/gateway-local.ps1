# Windows: run the G2 gateway natively (`make gateway-local`), on Windows' own
# Bluetooth stack: no usbipd, WSL distro or container involved. Arguments are
# passed to gateway_server.py.
#
# Installs into men-g2-ble-gateway\.venv with the same pinned packages as the
# Docker image (docker/gateway-constraints.txt). Uses uv when available, which
# also provides Python 3.12 (the image's version) without a system install;
# otherwise any working Python 3.10+.
$ErrorActionPreference = 'Stop'

$root  = Split-Path -Parent $PSScriptRoot
$gw    = Join-Path $root 'men-g2-ble-gateway'
$venv  = Join-Path $gw '.venv'
$py    = Join-Path $venv 'Scripts\python.exe'
# Relative to $root on purpose: uv misreads an absolute -c path that contains a
# space (e.g. C:\Users\John Lin\...) and fails with "Unexpected '['".
$req   = 'men-g2-ble-gateway\requirements.txt'
$pins  = 'docker\gateway-constraints.txt'

# The gateway container would hold port 8765 and the same glasses.
if (Get-Command docker -ErrorAction SilentlyContinue) {
    if (docker ps -q --filter 'name=^eveng2mount-gateway-1$' 2>$null) {
        Write-Host 'error: the gateway container is running. Stop it first: make down'
        exit 1
    }
}

function Find-Python {
    # Skips the Microsoft Store alias stubs, which exist but cannot run code.
    foreach ($cand in @(@('py', '-3'), @('python'), @('python3'))) {
        if (-not (Get-Command $cand[0] -ErrorAction SilentlyContinue)) { continue }
        $exe, $pre = $cand[0], @($cand | Select-Object -Skip 1)
        $ok = & $exe @pre -c 'import sys; print(sys.version_info >= (3, 10))' 2>$null
        if ($ok -eq 'True') { return , $cand }
    }
    return $null
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not (Test-Path $py)) {
    if ($uv) {
        Write-Host 'Creating men-g2-ble-gateway\.venv with uv (Python 3.12)...'
        uv venv --python 3.12 $venv
    } else {
        $sys = Find-Python
        if (-not $sys) {
            Write-Host 'error: no working Python found. Install uv (it provides Python itself):'
            Write-Host '  winget install astral-sh.uv'
            Write-Host 'then open a new terminal and run make gateway-local again.'
            exit 1
        }
        Write-Host "Creating men-g2-ble-gateway\.venv with $($sys -join ' ')..."
        $exe, $pre = $sys[0], @($sys | Select-Object -Skip 1)
        & $exe @pre -m venv $venv
    }
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}

# Quick no-op when everything is already installed.
Set-Location $root
if ($uv) {
    uv pip install --quiet --python $py -r $req -c $pins
} else {
    & $py -m pip install --quiet --disable-pip-version-check -r $req -c $pins
}
if ($LASTEXITCODE) { exit $LASTEXITCODE }

Set-Location $gw
& $py gateway_server.py @args
exit $LASTEXITCODE
