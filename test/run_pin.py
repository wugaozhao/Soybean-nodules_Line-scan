import os
import sys
import tkinter as tk
from tkinter import filedialog

# ===== 自动修复路径问题 =====
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)
# ============================

from pin import RootStitcher
import tkinter as tk
from tkinter import filedialog

# ===== 配置参数 =====
CONFIG = {
    "image_folder": r"D:\pycharm\pyqt5\photos\Ch23-1_11.24\rotation_IMG",
    "x_steps": 6,
    "z_steps": None,
    "step_size_mm": 39,
    "pixel_per_mm": 84.21,
    "overlap_pixels": 2142,
    "overlap_z_pixels": 3960,
    "fusion_method": "multiband",
    "balance_method": "clahe",
    "clahe_clip_limit": 2.0,
    "clahe_grid_size": (8, 8),
    "blend_border_width": 0,
    "scale_factor": 1.0
}


# ====================

def main():
    print("开始执行拼接...")
    print(f"当前目录: {CURRENT_DIR}")
    print(f"参数: {CONFIG}")

    stitcher = RootStitcher(**CONFIG)
    result = stitcher.run()

    # ===== 弹出文件保存对话框 =====
    # 创建根窗口并隐藏
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口

    # 设置默认文件名
    default_name = "stitched_result.png"

    # 弹出保存对话框
    output_path = filedialog.asksaveasfilename(
        title="保存拼接结果",
        initialdir=CONFIG["image_folder"],  # 初始目录
        initialfile=default_name,  # 默认文件名
        filetypes=[
            ("PNG图像", "*.png"),
            ("JPEG图像", "*.jpg;*.jpeg"),
            ("TIFF图像", "*.tiff;*.tif"),
            ("所有文件", "*.*")
        ],
        defaultextension=".png"  # 默认扩展名
    )

    # 检查用户是否取消了对话框
    if not output_path:
        print("❌ 取消保存操作")
        return

    # 确保目标目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 保存结果
    stitcher.save_result(output_path)
    print(f"✅ 拼接成功！文件保存至: {output_path}")


if __name__ == "__main__":
    main()