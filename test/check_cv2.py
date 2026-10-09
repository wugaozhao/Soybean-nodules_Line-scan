# check_cv2.py
import sys

print("=" * 60)
print(f"Python版本: {sys.version}")
print(f"Python路径: {sys.executable}")

# 检查关键包
packages = ['cv2', 'numpy', 'PIL', 'matplotlib']
for pkg in packages:
    try:
        module = __import__(pkg)
        version = getattr(module, '__version__', '未知版本')
        print(f"✓ {pkg}: {version}")
    except ImportError:
        print(f"✗ {pkg}: 未安装")
    except Exception as e:
        print(f"? {pkg}: 错误 - {e}")

print("=" * 60)

# 详细检查OpenCV
try:
    import cv2

    print(f"OpenCV详细版本: {cv2.__version__}")

    # 检查OpenCV路径
    import os

    cv2_path = os.path.dirname(cv2.__file__)
    print(f"OpenCV安装路径: {cv2_path}")

    # 检查可用的模块
    print("\nOpenCV可用模块:")
    modules = [name for name in dir(cv2) if not name.startswith('_')]
    print(f"共 {len(modules)} 个模块")

    # 测试基本功能
    import numpy as np

    test_img = np.zeros((10, 10, 3), dtype=np.uint8)
    print(f"测试图像创建成功: {test_img.shape}")

except Exception as e:
    print(f"OpenCV检查失败: {e}")
    import traceback

    traceback.print_exc()

input("\n按Enter键退出...")