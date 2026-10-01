# Windows: run BlueZ (the evenG2-bt WSL distro) in the background for the
# gateway container. Called by the Makefile:
#   bt.ps1 up     start BlueZ in a hidden window, unless it is already running
#   bt.ps1 down   stop it
#   bt.ps1 logs   show its log
#
# BlueZ must stay attached to a wsl.exe session, or WSL shuts the distro down
# when it goes idle. A hidden wsl.exe process is that session.
param([Parameter(Mandatory)][ValidateSet('up', 'down', 'logs')][string]$Action)

$Distro = 'evenG2-bt'

function Test-Installed {
    # Note: this starts the distro if it is installed but stopped.
    wsl.exe -d $Distro -- true 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Test-Running {
    wsl.exe -d $Distro -- pidof bluetoothd 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

switch ($Action) {
    'up' {
        if (-not (Test-Installed)) {
            Write-Host "BlueZ: $Distro is not installed (make bt-setup); continuing without Bluetooth."
            exit 0
        }
        if (Test-Running) {
            Write-Host 'BlueZ: already running.'
            exit 0
        }
        Start-Process wsl.exe -ArgumentList '-d', $Distro, '--', 'bluez-start', 'background' -WindowStyle Hidden
        for ($i = 0; $i -lt 20 -and -not (Test-Running); $i++) { Start-Sleep -Milliseconds 500 }
        if (Test-Running) {
            Write-Host 'BlueZ: started in the background (make bt-logs, make bt-down).'
        } else {
            Write-Host 'BlueZ: failed to start; see make bt-logs.'
            exit 1
        }
    }
    'down' {
        wsl.exe --terminate $Distro 2>$null | Out-Null
        Write-Host 'BlueZ: stopped.'
    }
    'logs' {
        wsl.exe -d $Distro -- cat /var/log/bluez.log
    }
}
