param(
    [string]$Python = "python",
    [ValidateSet("train", "val")]
    [string]$Split = "train"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ImageDir = Join-Path $ProjectRoot "data\nodule_coco\images\$Split"

& $Python -m labelme $ImageDir
