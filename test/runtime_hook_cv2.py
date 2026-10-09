# runtime_hook_cv2.py
import sys
import os


def fix_opencv_import():
    """修复OpenCV递归导入问题"""
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', '')

        # 修复OpenCV路径
        cv2_path = os.path.join(meipass, 'cv2')
        if os.path.exists(cv2_path):
            # 添加cv2路径到sys.path
            sys.path.insert(0, cv2_path)

            # 设置环境变量
            os.environ['PATH'] = cv2_path + os.pathsep + os.environ['PATH']

            print(f"[Runtime Hook] 设置OpenCV路径: {cv2_path}")

        # 修复PyQt5路径
        pyqt5_path = os.path.join(meipass, 'PyQt5')
        if os.path.exists(pyqt5_path):
            sys.path.insert(0, pyqt5_path)
            os.environ['PATH'] = pyqt5_path + os.pathsep + os.environ['PATH']


# 立即执行修复
fix_opencv_import()