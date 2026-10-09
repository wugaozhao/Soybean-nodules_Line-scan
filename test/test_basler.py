# test_basler.py
import sys
import os

print("=" * 70)
print("Basler相机程序依赖测试")
print("=" * 70)

# 模拟打包环境
if getattr(sys, 'frozen', False):
    print("运行模式: 打包exe")
else:
    print("运行模式: Python脚本")

# 测试导入
modules = [
    ('cv2', 'OpenCV'),
    ('numpy', 'NumPy'),
    ('PyQt5.QtWidgets', 'PyQt5'),
    ('pypylon', 'Basler pypylon'),
]

for module, name in modules:
    try:
        __import__(module)
        version = ""
        if module == 'cv2':
            import cv2

            version = cv2.__version__
        elif module == 'numpy':
            import numpy

            version = numpy.__version__
        elif module == 'PyQt5.QtWidgets':
            from PyQt5.QtCore import QT_VERSION_STR

            version = QT_VERSION_STR
        elif module == 'pypylon':
            import pypylon

            version = "installed"

        print(f"✓ {name}: {version}")
    except ImportError as e:
        print(f"✗ {name}: 导入失败 - {e}")
    except Exception as e:
        print(f"? {name}: 错误 - {e}")

print("\n" + "=" * 70)
print("测试完成")

# 测试OpenCV功能
try:
    import cv2
    import numpy as np

    test_img = np.zeros((100, 100, 3), dtype=np.uint8)
    print(f"OpenCV测试: 创建图像 {test_img.shape} 成功")
except:
    print("OpenCV功能测试失败")

# 测试PyQt5
try:
    from PyQt5.QtWidgets import QApplication

    print("PyQt5测试: 可以创建QApplication")
except:
    print("PyQt5测试失败")

input("\n按Enter退出...")