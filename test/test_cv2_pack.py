# test_cv2_pack.py
import sys
import traceback

print("=" * 60)
print("OpenCV 打包测试程序")

try:
    import cv2

    print(f"✓ OpenCV 导入成功: {cv2.__version__}")
except Exception as e:
    print(f"✗ OpenCV 导入失败: {e}")
    traceback.print_exc()

try:
    import numpy as np

    print(f"✓ NumPy 导入成功: {np.__version__}")

    # 测试基本功能
    test_img = np.zeros((50, 50, 3), dtype=np.uint8)
    print(f"✓ NumPy 数组创建成功: {test_img.shape}")

except Exception as e:
    print(f"✗ NumPy 导入失败: {e}")

print("\n环境信息:")
print(f"Python 路径: {sys.executable}")
print(f"运行模式: {'打包exe' if getattr(sys, 'frozen', False) else 'Python脚本'}")

if getattr(sys, 'frozen', False):
    print(f"MEIPASS: {getattr(sys, '_MEIPASS', '未设置')}")

print("=" * 60)
input("\n按 Enter 退出...")