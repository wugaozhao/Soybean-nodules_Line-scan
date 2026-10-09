param(
    [Parameter(Mandatory = $true)]
    [string]$Image,
    [string]$OutDir = "output\root_masks",
    [ValidateSet("cpu", "gpu")]
    [string]$Device = "cpu",
    [double]$Threshold = 0.5,
    [int]$TileSize = 512,
    [int]$Stride = 400,
    [switch]$SkipTraits,
    [switch]$SkipOverlay
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = "D:\anaconda3\envs\paddleseg\python.exe"
$Script = Join-Path $ProjectRoot "tools\predict_root_mask.py"

$argsList = @(
    $Script,
    $Image,
    "--out-dir", $OutDir,
    "--device", $Device,
    "--threshold", $Threshold,
    "--tile-size", $TileSize,
    "--stride", $Stride
)

if ($SkipTraits) {
    $argsList += "--skip-traits"
}
if ($SkipOverlay) {
    $argsList += "--skip-overlay"
}

& $Python @argsList
