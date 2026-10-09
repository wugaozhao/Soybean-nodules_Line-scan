# hook-cv2.py
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs
import os

# 收集OpenCV的所有文件
datas, binaries, hiddenimports = collect_all('cv2')

# 添加一些常见的隐藏导入
hiddenimports.extend([
    'cv2',
    'cv2.cv2',
    'cv2.data',
    'cv2.misc',
    'cv2.utils',
    'cv2.config',
    'cv2.load_config_py2',
    'cv2.load_config_py3',
    'numpy',
])

# 排除可能导致递归的文件
def _filter_binaries(binaries):
    filtered = []
    for dest, src in binaries:
        # 只保留必要的二进制文件
        if 'opencv' in src.lower():
            filtered.append((dest, src))
    return filtered

binaries = _filter_binaries(binaries)

print(f"OpenCV Hook 信息:")
print(f"  数据文件: {len(datas)}")
print(f"  二进制文件: {len(binaries)}")
print(f"  隐藏导入: {hiddenimports}")