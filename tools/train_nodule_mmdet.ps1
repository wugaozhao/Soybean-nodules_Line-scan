param(
    [string]$Python = "python",
    [string]$Config = "configs\mmdetection\nodule_cascade_mask_rcnn_r50_fpn_1024.py",
    [string]$WorkDir = "work_dirs\nodule\cascade_mask_rcnn_r50_fpn_1024",
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TrainScript = Join-Path $ProjectRoot "Thirdparty\mmdetection\tools\train.py"

$argsList = @($TrainScript, $Config, "--work-dir", $WorkDir)
if ($Resume) {
    $argsList += "--resume"
}

& $Python @argsList

