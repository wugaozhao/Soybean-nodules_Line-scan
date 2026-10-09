param(
    [Parameter(Mandatory = $true)]
    [string]$Checkpoint,
    [string]$Python = "python",
    [string]$Config = "configs\mmdetection\nodule_cascade_mask_rcnn_r50_fpn_1024.py",
    [string]$Out = "work_dirs\nodule\predictions.pkl",
    [switch]$Show
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TestScript = Join-Path $ProjectRoot "Thirdparty\mmdetection\tools\test.py"

$argsList = @($TestScript, $Config, $Checkpoint, "--out", $Out)
if ($Show) {
    $argsList += "--show"
}

& $Python @argsList

