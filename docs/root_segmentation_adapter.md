# PaddleSeg 根系分割适配说明

本适配层使用已有的 PaddleSeg 根系模型：

- `Thirdparty/Paddleseg/root_get/segformer_cotton_root_1024x1024_150k.yml`
- `Thirdparty/Paddleseg/root_get/model.pdparams`
- `Thirdparty/Paddleseg/PaddleSeg-release-2.10/paddleseg`

`Thirdparty/` 和模型权重默认不会提交到 GitHub。新环境需要自行下载
PaddleSeg 2.10 源码，并将合法取得的根系模型配置及权重放到上述路径。
数据集、实验输出和权重应通过机构存储、对象存储或带访问控制的发布页单独共享，
不要直接提交到普通 Git 历史。

`D:\A_Project\PaddleSeg-release-2.10` 中的完整上游项目视为只读，不会被修改。适配层使用本项目 `Thirdparty/Paddleseg/` 下的副本。

配置文件会被直接解析，当前默认参数为：

- 模型：`SegFormer_B2`
- 类别数：`2`
- 前景类别：`1`
- 切块大小：`512`
- 切块步长：`400`
- 归一化：`mean=(0.5, 0.5, 0.5)`，`std=(0.5, 0.5, 0.5)`

为兼容 PaddleSeg 2.10，适配层会将项目配置中的简写：

```yaml
model:
  type: SegFormer_B2
```

转换为 PaddleSeg 2.10 的标准配置结构：

```yaml
model:
  type: SegFormer
  backbone:
    type: MixVisionTransformer_B2
    pretrained: null
  embedding_dim: 768
  num_classes: 2
```

运行时配置会写入临时文件，并在模型加载完成后删除；原始训练配置不会被修改。

使用 GPU 预测：

```powershell
python tools\predict_root_mask.py output\Date0810\3_900.bmp --device gpu
```

CPU 备用预测：

```powershell
python tools\predict_root_mask.py output\Date0810\3_900.bmp --device cpu
```

默认输出目录为 `output/root_masks/`：

- `{image}_root_mask.png`：原始二值根系掩膜
- `{image}_root_mask_clean.png`：清理后的二值根系掩膜
- `{image}_root_overlay.jpg`：降采样质检叠加图
- `{image}_root_traits.csv`：根系面积、骨架长度、连通域数、端点数和分叉点数
- `{image}_root_traits.json`：与 CSV 相同的性状结果，JSON 格式

请在实际运行分析的环境中安装依赖。Python 版本应与 PaddlePaddle 版本兼容，推荐 Python 3.10 或 3.11：

```powershell
python -m pip install -r requirements_phenotyping.txt
```

注意事项：

- 当前仓库的 Anaconda OpenCV 与 `numpy 2.1.3` 不兼容。因此根系性状计算不依赖 `cv2`，而使用 `Pillow`、`numpy`、`scipy` 和 `scikit-image`。
- PaddleSeg 本身会导入 OpenCV，因此分析环境应使用 `numpy<2` 和 `opencv-python<=4.6.0`，与 PaddleSeg 2.10 的依赖要求保持一致。
- 提供的模型文件是 PaddleSeg 动态图权重（`.pdparams`），不是导出的 Paddle Inference 模型。因此适配层通过 PaddleSeg 的 `Config` 和 `SegBuilder` 加载模型。
- 对于 `15552 x 25344` 的整图，根系骨架化可能占用较多内存和时间。若处理速度过慢，下一步应采用分块根长估计，或导出 PaddleSeg 模型以加速推理。
