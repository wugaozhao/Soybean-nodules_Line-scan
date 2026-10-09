# Third-Party Instance-Segmentation Repositories

`Thirdparty/` is intentionally excluded from Git because these projects have
their own repositories and histories. After cloning this project, recreate the
local dependencies from the project root with:

```powershell
New-Item -ItemType Directory -Force Thirdparty | Out-Null
git clone https://github.com/open-mmlab/mmdetection.git Thirdparty/mmdetection
git clone https://github.com/obss/sahi.git Thirdparty/sahi
git clone https://github.com/wkentaro/labelme.git Thirdparty/labelme

git -C Thirdparty/mmdetection checkout cfd5d3a985b0249de009b67d04f37263e11cdf3d
git -C Thirdparty/sahi checkout c93524bac3120e3bd04ecbf7359ee71165507c6b
git -C Thirdparty/labelme checkout 1741c875d84df63e1b62ea6ee9270196a23dfcce
```

The repositories are used for nodule instance segmentation and dataset
preparation as follows.

| Directory | Upstream | Role |
|---|---|---|
| `Thirdparty/mmdetection` | `https://github.com/open-mmlab/mmdetection` | Main training and evaluation framework for Cascade Mask R-CNN, ConvNeXt Cascade Mask R-CNN, and Mask2Former. |
| `Thirdparty/sahi` | `https://github.com/obss/sahi` | Reference and optional integration for sliced inference on large images. |
| `Thirdparty/labelme` | `https://github.com/wkentaro/labelme` | Local polygon annotation tool. |

Validated commits:

```text
mmdetection: cfd5d3a
sahi: c93524b
labelme: 1741c87
```

Project-specific files are not placed inside these repositories. Keep local modifications in:

- `tools/`
- `src/phenotyping/`
- `configs/mmdetection/`
- `docs/`

