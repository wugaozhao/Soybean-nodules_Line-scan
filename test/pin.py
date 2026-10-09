import sys
import cv2
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
import warnings
import argparse


class RootStitcher:
    """
    微观根系图像拼接器
    适用于蛇形扫描轨迹采集的图像序列
    """

    def __init__(self, image_folder: str, x_steps: int, z_steps: Optional[int] = None,
                 step_size_mm: float = 1.0, pixel_per_mm: Optional[float] = None,
                 overlap_pixels: Optional[int] = None,
                 overlap_z_pixels: Optional[int] = None,
                 discard_last_row: bool = True,
                 fusion_method: str = 'multiband',
                 balance_method: str = 'clahe',
                 clahe_clip_limit: float = 2.5,
                 clahe_grid_size: tuple = (16, 16), scale_factor=1.0,
                 blend_border_width: int = 0):  # ✅ 默认0：硬拼接模式
        """
        参数说明：
        :param image_folder: 图像文件夹路径（包含IMG子文件夹）
        :param x_steps: X轴每行步数（固定列数）
        :param z_steps: Z轴总行数（如果为None则自动计算，舍弃不完整行）
        :param step_size_mm: 步进长度(mm)，默认1.0mm
        :param pixel_per_mm: 像素当量（像素/mm），必需参数
        :param overlap_pixels: 水平方向重叠像素数（如果提供则忽略其他计算）
        :param overlap_z_pixels: 垂直方向重叠像素数（独立控制，如果为None则使用overlap_pixels）
        :param discard_last_row: 是否舍弃不完整的最后一行（默认True）
        :param fusion_method: 融合方法 'feather'或'multiband'
        :param balance_method: 亮度均衡方法 'none', 'gaussian', 'clahe'
        :param clahe_clip_limit: CLAHE对比度限制
        :param clahe_grid_size: CLAHE网格大小
        :param blend_border_width: 边界融合宽度（像素），0=硬拼接（默认），>0=边界融合
        """
        # 参数验证
        if overlap_pixels is None and pixel_per_mm is None:
            raise ValueError("必须提供 overlap_pixels 或 pixel_per_mm 参数")

        if x_steps <= 0:
            raise ValueError("x_steps 必须为正整数")

        self.image_folder = Path(image_folder) / "IMG"
        self.x_steps = x_steps
        self.z_steps = z_steps
        self.step_size_mm = step_size_mm
        self.pixel_per_mm = pixel_per_mm
        self.overlap_pixels = overlap_pixels
        self.overlap_z_pixels = overlap_z_pixels
        self.discard_last_row = discard_last_row
        self.fusion_method = fusion_method
        self.balance_method = balance_method
        self.clahe_clip_limit = clahe_clip_limit
        self.clahe_grid_size = clahe_grid_size
        self.scale_factor = scale_factor
        self.blend_border_width = blend_border_width
        self.image_width = None
        self.image_height = None

        # 计算状态
        self.images: List[np.ndarray] = []
        self.positions: List[Tuple[int, int]] = []
        self.canvas: Optional[np.ndarray] = None

        print(f"初始化拼接器:")
        print(f"  图像目录: {self.image_folder}")
        print(f"  X轴步数: {x_steps} (每行{x_steps}张图像)")
        print(f"  Z轴步数: {z_steps if z_steps else '自动计算'}")
        print(f"  步长: {step_size_mm}mm")
        print(f"  亮度均衡: {balance_method}, clip_limit={clahe_clip_limit}")
        if pixel_per_mm:
            print(f"  像素当量: {pixel_per_mm} pixel/mm")
        if overlap_pixels:
            print(f"  水平重叠: {overlap_pixels} pixels")
        if overlap_z_pixels:
            print(f"  垂直重叠: {overlap_z_pixels} pixels")
        print(f"  融合模式: {'硬拼接' if blend_border_width == 0 else f'边界融合({blend_border_width}px)'}")

    def load_images(self) -> List[np.ndarray]:
        """加载所有图像，自动计算完整行数"""
        if not self.image_folder.exists():
            raise FileNotFoundError(f"图像目录不存在: {self.image_folder}")

        # 查找所有auto_capture图像
        image_paths = sorted(self.image_folder.glob("auto_capture_*.png"))
        if not image_paths:
            raise ValueError(f"在 {self.image_folder} 中未找到 auto_capture_*.png 图像")

        total_images = len(image_paths)
        print(f"  发现 {total_images} 张图像")

        # 计算完整行数（舍弃不完整行）
        complete_rows = total_images // self.x_steps
        if complete_rows == 0:
            raise ValueError(f"图像数量不足: 至少需要 {self.x_steps} 张图像组成一行")

        usable_images = complete_rows * self.x_steps
        self.z_steps = complete_rows

        if self.discard_last_row and usable_images < total_images:
            warnings.warn(f"舍弃 {total_images - usable_images} 张不完整的最后一行图像")
            print(f"  实际使用: {usable_images} 张图像 ({complete_rows}行 × {self.x_steps}列)")

        # 加载图像
        self.images = []
        for i, path in enumerate(image_paths[:usable_images]):
            img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if img is None:
                raise IOError(f"无法读取图像: {path}")
            if img.dtype == np.uint16:
                img = (img / 256).clip(0, 255).astype(np.uint8)
            self.images.append(img)

        print(f"  成功加载 {len(self.images)} 张图像")

        # 记录原始图像尺寸
        if self.images:
            self.image_height, self.image_width = self.images[0].shape[:2]
            print(f"  原始图像尺寸: {self.image_width}×{self.image_height}")

        # 缩放图像
        if self.scale_factor != 1.0:
            print(f"  缩放图像，因子: {self.scale_factor}")
            new_width = int(self.image_width * self.scale_factor)
            new_height = int(self.image_height * self.scale_factor)
            self.images = [cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_AREA) for img in
                           self.images]

            if self.overlap_pixels is not None:
                self.overlap_pixels = int(self.overlap_pixels * self.scale_factor)
                print(f"  缩放水平重叠像素至: {self.overlap_pixels}")

            if self.overlap_z_pixels is not None:
                self.overlap_z_pixels = int(self.overlap_z_pixels * self.scale_factor)
                print(f"  缩放垂直重叠像素至: {self.overlap_z_pixels}")

            self.image_width = new_width
            self.image_height = new_height
            print(f"  缩放后图像尺寸: {self.image_width}×{self.image_height}")

        return self.images

    def preprocess_image(self, img: np.ndarray) -> np.ndarray:
        """亮度均衡化预处理"""
        if len(img.shape) == 3 and img.shape[2] == 3:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)

            if self.balance_method == 'clahe':
                clahe = cv2.createCLAHE(
                    clipLimit=self.clahe_clip_limit,
                    tileGridSize=self.clahe_grid_size
                )
                l_corrected = clahe.apply(l)
            elif self.balance_method == 'gaussian':
                background = cv2.GaussianBlur(l, (51, 51), 50)
                l_corrected = cv2.subtract(l, background.astype(np.int16))
                l_corrected = cv2.normalize(l_corrected, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            else:
                l_corrected = l

            lab_corrected = cv2.merge([l_corrected, a, b])
            result = cv2.cvtColor(lab_corrected, cv2.COLOR_LAB2BGR)
        else:
            if self.balance_method == 'clahe':
                clahe = cv2.createCLAHE(
                    clipLimit=self.clahe_clip_limit,
                    tileGridSize=self.clahe_grid_size
                )
                result = clahe.apply(img)
            elif self.balance_method == 'gaussian':
                background = cv2.GaussianBlur(img, (51, 51), 50)
                corrected = cv2.subtract(img, background.astype(np.int16))
                result = cv2.normalize(corrected, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            else:
                result = img

        return result

    def calculate_overlap(self, img_width: int, img_height: Optional[int] = None) -> Tuple[int, int]:
        """
        计算重叠像素
        返回: (horizontal_overlap, vertical_overlap)
        """
        # 水平重叠
        if self.overlap_pixels is not None:
            overlap_x = self.overlap_pixels
        else:
            fov_mm = img_width / self.pixel_per_mm
            step_pixels = self.step_size_mm * self.pixel_per_mm
            overlap_x = int(img_width - step_pixels)
            if overlap_x <= 0:
                warnings.warn(f"计算出的水平重叠像素数为{overlap_x}，可能导致拼接失败")
                overlap_x = max(0, overlap_x)

        # 垂直重叠（独立设置）
        if self.overlap_z_pixels is not None:
            overlap_z = self.overlap_z_pixels
        elif img_height is not None and self.pixel_per_mm is not None:
            fov_mm_z = img_height / self.pixel_per_mm
            step_pixels_z = self.step_size_mm * self.pixel_per_mm
            overlap_z = int(img_height - step_pixels_z)
            warnings.warn(f"垂直重叠像素未指定，自动计算为: {overlap_z}")
        else:
            overlap_z = overlap_x
            warnings.warn(f"垂直重叠像素未指定，使用水平重叠值: {overlap_z}")

        # 确保重叠像素不超过图像尺寸
        overlap_x = min(overlap_x, img_width - 1)
        if img_height is not None:
            overlap_z = min(overlap_z, img_height - 1)

        print(f"  图像尺寸: {img_width}×{img_height}")
        print(f"  重叠像素: 水平={overlap_x}, 垂直={overlap_z}")
        return overlap_x, overlap_z

    def calculate_positions(self) -> List[Tuple[int, int]]:
        """计算蛇形布局中每个图像的理论位置"""
        if not self.images:
            raise ValueError("请先加载图像")

        h, w = self.images[0].shape[:2]
        overlap_x, overlap_z = self.calculate_overlap(w, h)

        step_x = w - overlap_x
        step_z = h - overlap_z

        if step_x <= 0:
            raise ValueError(f"计算出的X方向步长({step_x})无效，请检查水平重叠像素设置")
        if step_z <= 0:
            raise ValueError(f"计算出的Z方向步长({step_z})无效，请检查垂直重叠像素设置")

        self.positions = []
        for idx in range(len(self.images)):
            z = idx // self.x_steps
            x = idx % self.x_steps
            if z % 2 == 1:
                x = self.x_steps - 1 - x
            self.positions.append((x * step_x, z * step_z))

        print(f"  单图尺寸: {w}×{h}, 步长: {step_x}×{step_z}")
        return self.positions

    # ✅ 仅边界窄带融合权重
    def _create_border_blend_weights(self, shape: Tuple[int, int]) -> np.ndarray:
        """
        创建仅边界窄带融合权重矩阵
        - 中心区域权重=1（直接覆盖）
        - 仅边界blend_border_width像素范围做线性渐变
        """
        h, w = shape[:2]
        weights = np.ones((h, w), dtype=np.float32)

        # 边界宽度（限制最大为图像宽度的1/8）
        border_width = min(self.blend_border_width, w // 8)

        if border_width > 0:
            # 左侧边界：0→1 渐变（仅边缘窄带）
            weights[:, :border_width] *= np.linspace(0, 1, border_width)

            # 右侧边界：1→0 渐变（仅边缘窄带）
            weights[:, -border_width:] *= np.linspace(1, 0, border_width)

        # 如果是彩色图像，扩展权重到3通道
        if len(shape) == 3 and shape[2] == 3:
            weights = weights[:, :, np.newaxis]

        return weights

    def stitch_images(self) -> np.ndarray:
        if not self.images:
            raise ValueError("没有加载的图像")

        h, w = self.images[0].shape[:2]
        overlap_x, overlap_z = self.calculate_overlap(w, h)

        # 画布尺寸
        canvas_width = (w - overlap_x) * (self.x_steps - 1) + w
        canvas_height = (h - overlap_z) * (self.z_steps - 1) + h
        num_channels = 1 if len(self.images[0].shape) == 2 else self.images[0].shape[2]
        canvas_shape = (canvas_height, canvas_width, num_channels) if num_channels > 1 else (canvas_height,
                                                                                             canvas_width)

        print(f"  画布尺寸: {canvas_width}×{canvas_height}")

        # ✅ 关键修改：根据blend_border_width选择模式
        if self.blend_border_width <= 0:
            # ✅ 硬拼接模式：直接覆盖（最清晰）
            print("  硬拼接模式（无融合，直接覆盖）...")
            self.canvas = np.zeros(canvas_shape, dtype=np.uint8)

            for idx, (img, (x, z)) in enumerate(zip(self.images, self.positions)):
                slice_y = slice(z, z + img.shape[0])
                slice_x = slice(x, x + img.shape[1])

                # 直接内存复制，无权重计算
                if len(img.shape) == 2 and len(self.canvas.shape) == 3:
                    img = img[..., np.newaxis]

                self.canvas[slice_y, slice_x] = img
        else:
            # ✅ 边界融合模式：仅边界窄带融合
            print(f"  边界融合模式（宽度={self.blend_border_width}px）...")
            canvas_sum = np.zeros(canvas_shape, dtype=np.float32)
            canvas_weights = np.zeros(canvas_shape, dtype=np.float32)

            # 第一遍：计算加权和（仅边界融合）
            for idx, (img, (x, z)) in enumerate(zip(self.images, self.positions)):
                img_h, img_w = img.shape[:2]
                slice_y = slice(z, z + img_h)
                slice_x = slice(x, x + img_w)

                # 仅在图像边界创建窄带融合权重
                weights = self._create_border_blend_weights(img.shape)

                img_float = img.astype(np.float32)
                if len(img.shape) == 2:
                    img_float = img_float[..., np.newaxis]
                    weights = weights[..., np.newaxis]

                canvas_sum[slice_y, slice_x] += img_float * weights
                canvas_weights[slice_y, slice_x] += weights

            # 第二遍：归一化
            canvas_weights[canvas_weights == 0] = 1
            self.canvas = (canvas_sum / canvas_weights).astype(np.uint8)

        return self.canvas

    def visualize_layout(self) -> np.ndarray:
        if not self.positions:
            raise ValueError("请先计算位置")

        canvas = np.zeros((self.canvas.shape[0], self.canvas.shape[1]), dtype=np.uint8)

        for idx, (img, (x, z)) in enumerate(zip(self.images, self.positions)):
            cv2.rectangle(canvas, (x, z), (x + img.shape[1], z + img.shape[0]),
                          (255, 255, 255), 2)
            cv2.putText(canvas, str(idx + 1), (x + 10, z + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)

        return canvas

    def crop_to_content(self) -> np.ndarray:
        if self.canvas is None:
            raise ValueError("请先执行拼接")

        if len(self.canvas.shape) == 3:
            gray = cv2.cvtColor(self.canvas, cv2.COLOR_BGR2GRAY)
        else:
            gray = self.canvas

        row_sum = np.sum(gray, axis=1)
        col_sum = np.sum(gray, axis=0)

        rows_nonzero = np.where(row_sum > 0)[0]
        cols_nonzero = np.where(col_sum > 0)[0]

        if len(rows_nonzero) == 0 or len(cols_nonzero) == 0:
            warnings.warn("未找到有效内容区域")
            return self.canvas

        y0, y1 = rows_nonzero[0], rows_nonzero[-1]
        x0, x1 = cols_nonzero[0], cols_nonzero[-1]

        if len(self.canvas.shape) == 3:
            cropped = self.canvas[y0:y1 + 1, x0:x1 + 1, :]
        else:
            cropped = self.canvas[y0:y1 + 1, x0:x1 + 1]

        print(f"  裁剪后尺寸: {cropped.shape[1]}×{cropped.shape[0]}")
        return cropped

    def run(self, visualize: bool = False) -> np.ndarray:
        print("===== 开始根系图像拼接 =====")
        print(f"步骤1: 加载图像...")
        self.load_images()

        print(f"步骤2: 预处理...")
        self.images = [self.preprocess_image(img) for img in self.images]

        print(f"步骤3: 计算位置...")
        self.calculate_positions()

        print(f"步骤4: 拼接...")
        self.stitch_images()

        print(f"步骤5: 裁剪优化...")
        result = self.crop_to_content()
        self.canvas = result

        if visualize:
            print(f"步骤6: 生成布局图...")
            layout_viz = self.visualize_layout()
            return result, layout_viz

        print(f"===== 拼接完成 =====")
        return result

    def save_result(self, output_path: str, result: Optional[np.ndarray] = None):
        if result is None:
            result = self.canvas
        if result is None:
            raise ValueError("没有可保存的结果")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(output_path, result)

        # 验证保存的文件尺寸和质量
        saved_img = cv2.imread(output_path)
        print(f"✅ 结果已保存: {output_path}")
        print(f"  文件尺寸: {saved_img.shape[1]}×{saved_img.shape[0]}")
        print(f"  数据类型: {saved_img.dtype}")

        # 检查是否清晰（计算模糊度指标）
        gray = cv2.cvtColor(saved_img, cv2.COLOR_BGR2GRAY) if len(saved_img.shape) == 3 else saved_img
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        print(f"  清晰度指标: {laplacian_var:.2f}（值越大越清晰）")


def main():
    """命令行使用示例"""
    parser = argparse.ArgumentParser(description="微观根系图像拼接工具")
    parser.add_argument("folder", help="图像主文件夹路径")
    parser.add_argument("--x-steps", type=int, required=True, help="X轴步数")
    parser.add_argument("--z-steps", type=int, help="Z轴步数（可选，自动计算）")
    parser.add_argument("--step-size", type=float, default=1.0, help="步长(mm)")
    parser.add_argument("--pixel-per-mm", type=float, help="像素当量(pixel/mm)")
    parser.add_argument("--overlap", type=int, help="水平重叠像素数")
    parser.add_argument("--overlap-z", type=int, help="垂直重叠像素数")
    parser.add_argument("--blend-width", type=int, default=0, help="边界融合宽度（像素），0=硬拼接（默认）")  # ✅ 修改默认值
    parser.add_argument("--output", default="stitched_root.png", help="输出路径")
    parser.add_argument("--visualize", action="store_true", help="生成布局可视化图")

    args = parser.parse_args()

    try:
        # 创建拼接器
        stitcher = RootStitcher(
            image_folder=args.folder,
            x_steps=args.x_steps,
            z_steps=args.z_steps,
            step_size_mm=args.step_size,
            pixel_per_mm=args.pixel_per_mm,
            overlap_pixels=args.overlap,
            overlap_z_pixels=args.overlap_z,
            fusion_method='multiband',
            blend_border_width=args.blend_width
        )

        # 执行拼接
        if args.visualize:
            result, layout = stitcher.run(visualize=True)
            layout_path = str(Path(args.output).with_suffix('.layout.png'))
            stitcher.save_result(layout_path, layout)
        else:
            result = stitcher.run()

        # 保存结果
        stitcher.save_result(args.output, result)

        # 显示结果
        plt.figure(figsize=(12, 8))
        if len(result.shape) == 3:
            plt.imshow(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))
        else:
            plt.imshow(result, cmap='gray')
        plt.title("拼接结果")
        plt.axis('off')
        plt.show()

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())