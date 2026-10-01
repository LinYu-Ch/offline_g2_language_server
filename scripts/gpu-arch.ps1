# Print this machine's NVIDIA compute capabilities in CMAKE_CUDA_ARCHITECTURES
# form, e.g. "89" or "86;89". Prints nothing if there is no NVIDIA GPU.
# Called by the Makefile for GPU=1 builds on Windows.
#
# A 32-bit caller such as GnuWin32 make is redirected away from System32, where
# nvidia-smi lives; Sysnative is the 32-bit view of the real System32.
$smi = Join-Path $env:windir 'Sysnative\nvidia-smi.exe'
if (-not (Test-Path $smi)) { $smi = 'nvidia-smi' }
try {
    $caps = & $smi --query-gpu=compute_cap --format=csv,noheader 2>$null
} catch {
    exit 0
}
($caps | ForEach-Object { $_.Trim().Replace('.', '') } | Where-Object { $_ } | Sort-Object -Unique) -join ';'
