# 大豆根瘤实例分割数据集与模型流程

本流程用于构建高精度根瘤实例分割数据集，并训练 MMDetection 模型。根系分割继续使用已有的 PaddleSeg 模型。

## 第三方项目

这些项目应按 `docs/thirdparty_instance_segmentation.md` 的说明克隆到本机
`Thirdparty/` 目录（该目录不提交到当前仓库）：

- `Thirdparty/mmdetection`：实例分割训练与评估框架。
- `Thirdparty/sahi`：超大图像切片推理的参考/可选工具。
- `Thirdparty/labelme`：多边形标注工具。

不要直接修改上述第三方仓库中的项目逻辑。项目专用脚本放在 `tools/`，模型配置放在 `configs/mmdetection/`，分析代码放在 `src/phenotyping/`。

## 数据集结构

数据集采用 COCO 实例分割格式，仅包含一个类别：`nodule`。

```text
data/nodule_coco/
  images/
    train/
      *.jpg
      *.json        # 标注期间生成的 LabelMe 标注文件
    val/
      *.jpg
      *.json
  annotations/
    instances_train.json
    instances_val.json
    tiles_train.csv
    tiles_val.csv
```

每一个根瘤必须标注为一个独立实例，标签必须严格写为：

```text
nodule
```

## 第 1 步：生成切片

从全分辨率图像生成训练切片：

```powershell
python tools\make_nodule_tiles.py output\Date0810\3_900.bmp --split train --tile-size 1024 --stride 768 --format jpg --quality 95 --extensions bmp
```

切片文件名包含源图像相对目录和稳定短哈希。因此 `Date0810\1.bmp` 与 `Date0820\1.bmp` 可以放入同一数据集划分，不会相互覆盖。一次处理多个采集日期时，请显式传入每个日期目录，以避免处理 `output` 下可能存在的预览图和其他派生图像：

```powershell
python tools\make_nodule_tiles.py output\Date0810 output\Date0820 --split train --tile-size 1024 --stride 768 --format jpg --quality 95 --extensions bmp
```

重复执行命令时，默认跳过已有切片，并合并 `annotations\tiles_train.csv`，从而保留已完成的 LabelMe 标注。仅在尚未标注时使用 `--existing overwrite`；使用 `--existing error` 可以检查重复输入。

从不同源图像或人工选定区域生成验证集切片：

```powershell
python tools\make_nodule_tiles.py output\Date0810\3_750.bmp --split val --tile-size 1024 --stride 768 --format jpg --quality 95 --extensions bmp
```

首批数据集建议：

- 标注 300-800 张训练切片。
- 标注 80-150 张验证切片。
- 包含有根瘤的正样本，也包含只有根系、反光、杂质、气泡、容器边缘而没有根瘤的困难负样本。
- 优先标注根系附近的切片，避免在大面积纯背景上耗费标注时间。

若已有全分辨率根系掩膜，可按根系掩膜覆盖率过滤切片：

```powershell
python tools\make_nodule_tiles.py output\Date0810\3_900.bmp --split train --roi-mask output\root_masks\3_900_root_mask_clean.png --min-roi-fraction 0.002
```

## 第 2 步：使用 LabelMe 标注

在 GPU 训练环境中安装 LabelMe：

```powershell
pip install -e Thirdparty\labelme
```

打开训练集切片：

```powershell
powershell -ExecutionPolicy Bypass -File tools\open_labelme_nodule.ps1 -Split train
```

打开验证集切片：

```powershell
powershell -ExecutionPolicy Bypass -File tools\open_labelme_nodule.ps1 -Split val
```

标注规则：

- 对普通根瘤使用多边形，不使用仅有框的标注方式。
- 每个根瘤绘制一个独立多边形。
- 标签必须为 `nodule`。
- 对相互接触的根瘤，若人工可以区分边界，应绘制为不同多边形。
- 根段、气泡、杂质、反光和容器边缘均不标为根瘤。
- 保留无根瘤的负样本切片，用于降低误检率。

## 第 3 步：将 LabelMe 转为 COCO

```powershell
python tools\labelme_to_coco_nodule.py --split train
python tools\labelme_to_coco_nodule.py --split val
```

验证数据集：

```powershell
python tools\validate_nodule_coco.py --split train
python tools\validate_nodule_coco.py --split val
```

校验脚本会检查：

- 图像文件是否存在。
- 类别是否严格为 `nodule`。
- 多边形、边界框和面积是否有效。
- 正样本与空白切片的数量。

## 第 4 步：安装 MMDetection 环境

在 NVIDIA 2080 主机上，优先使用已可用的 CUDA/PyTorch 环境。若尚未安装 MMDetection，则执行：

```powershell
pip install -U openmim
mim install mmengine
mim install "mmcv>=2.0.0"
pip install -e Thirdparty\mmdetection
pip install mmpretrain
```

`mmpretrain` 是 ConvNeXt 配置的必需依赖；R50 Cascade Mask R-CNN 配置不需要它。

## 第 5 步：训练模型

稳定的基线模型：

```powershell
powershell -ExecutionPolicy Bypass -File tools\train_nodule_mmdet.ps1 `
  -Config configs\mmdetection\nodule_cascade_mask_rcnn_r50_fpn_1024.py `
  -WorkDir work_dirs\nodule\cascade_mask_rcnn_r50_fpn_1024
```

更强的特征提取模型：

```powershell
powershell -ExecutionPolicy Bypass -File tools\train_nodule_mmdet.ps1 `
  -Config configs\mmdetection\nodule_cascade_mask_rcnn_convnext_t_1024.py `
  -WorkDir work_dirs\nodule\cascade_mask_rcnn_convnext_t_1024
```

用于比较边界和粘连根瘤分割的模型：

```powershell
powershell -ExecutionPolicy Bypass -File tools\train_nodule_mmdet.ps1 `
  -Config configs\mmdetection\nodule_mask2former_swin_t_1024.py `
  -WorkDir work_dirs\nodule\mask2former_swin_t_1024
```

先训练 R50 Cascade 模型。数据集通过校验且基线模型产生合理预测后，再训练 ConvNeXt 或 Mask2Former 进行对比。

## 第 6 步：评估模型

```powershell
powershell -ExecutionPolicy Bypass -File tools\test_nodule_mmdet.ps1 `
  -Config configs\mmdetection\nodule_cascade_mask_rcnn_r50_fpn_1024.py `
  -Checkpoint work_dirs\nodule\cascade_mask_rcnn_r50_fpn_1024\best_coco_segm_mAP_epoch_*.pth
```

重点关注的指标：

- `segm_mAP`
- `segm_mAP_50`
- `segm_mAP_75`
- 验证集切片上的根瘤数量 MAE
- 困难负样本上的误检数
- 粘连根瘤的分裂错误和合并错误

## 模型使用顺序

建议按以下顺序训练和比较：

1. `nodule_cascade_mask_rcnn_r50_fpn_1024.py`
   - 稳定、易调试、显存占用较低。
2. `nodule_cascade_mask_rcnn_convnext_t_1024.py`
   - 特征提取能力更强，适用于基线模型欠拟合的情况。
3. `nodule_mask2former_swin_t_1024.py`
   - 当粘连根瘤或边界分割仍是主要误差来源时使用。

## 后续工程步骤

获得第一个训练完成的模型权重后，增加整图切片推理流程：

```text
完整 BMP 图像
  -> 1024 或 1536 像素的重叠切片
  -> MMDetection 实例预测
  -> 将掩膜映射回整图坐标
  -> 基于掩膜 IoU 的重复实例去除
  -> 按根系掩膜距离过滤
  -> 输出每个根瘤的 CSV 和质检叠加图
```

不要只依据切片 mAP 判断最终效果。最终目标是整图层面的根瘤数量，以及根瘤相对于根系的分布性状。
