#简易拍摄，四角拼接

import sys
import os
import cv2
import numpy as np
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGroupBox, QLabel, QPushButton,
                             QTextEdit, QFileDialog)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QThread
from PyQt5.QtGui import QImage, QPixmap
import warnings
warnings.filterwarnings("ignore")

# 尝试导入 Basler SDK
try:
    from pypylon import pylon
    BASLER_SUPPORT = True
except ImportError:
    BASLER_SUPPORT = False
    print("pypylon 未安装，Basler相机不可用")

# ----------------------------- 相机线程 -----------------------------
class CameraThread(QThread):
    frame_signal = pyqtSignal(np.ndarray)
    error_signal = pyqtSignal(str)

    def __init__(self, use_basler=False):
        super().__init__()
        self.use_basler = use_basler
        self.is_running = False
        self.camera = None
        self.converter = None

    def run(self):
        try:
            if self.use_basler and BASLER_SUPPORT:
                # Basler 相机初始化
                self.converter = pylon.ImageFormatConverter()
                self.converter.OutputPixelFormat = pylon.PixelType_BGR8packed
                self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned
                tl_factory = pylon.TlFactory.GetInstance()
                devices = tl_factory.EnumerateDevices()
                if not devices:
                    self.error_signal.emit("未找到Basler相机")
                    return
                self.camera = pylon.InstantCamera(tl_factory.CreateDevice(devices[0]))
                self.camera.Open()
                # 设置基础参数
                try:
                    self.camera.ExposureTime.SetValue(35000)      # 曝光时间 35000 µs
                    self.camera.BalanceWhiteAuto.SetValue("Once") # 自动白平衡
                    self.camera.AcquisitionFrameRateEnable.SetValue(True)
                    self.camera.AcquisitionFrameRate.SetValue(15)
                except Exception as e:
                    self.error_signal.emit(f"相机参数设置失败: {e}")
                self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
                self.is_running = True
                while self.is_running and self.camera.IsGrabbing():
                    grab_result = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
                    if grab_result.GrabSucceeded():
                        image = self.converter.Convert(grab_result)
                        frame = image.GetArray()
                        self.frame_signal.emit(frame)
                    grab_result.Release()
            else:
                # USB 相机（OpenCV）
                self.camera = cv2.VideoCapture(0)
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.camera.set(cv2.CAP_PROP_FPS, 30)
                if not self.camera.isOpened():
                    self.error_signal.emit("无法打开USB相机")
                    return
                self.is_running = True
                while self.is_running:
                    ret, frame = self.camera.read()
                    if ret:
                        self.frame_signal.emit(frame)
                    else:
                        self.error_signal.emit("读取相机帧失败")
                        break
        except Exception as e:
            self.error_signal.emit(f"相机错误: {str(e)}")
        finally:
            if self.camera:
                if self.use_basler and BASLER_SUPPORT:
                    self.camera.StopGrabbing()
                    self.camera.Close()
                else:
                    self.camera.release()

    def stop(self):
        self.is_running = False
        self.wait()

# ----------------------------- 主窗口 -----------------------------
class CameraApp(QMainWindow):
    def __init__(self):
        super().__init__()
        # 相机相关
        self.camera_thread = None
        self.current_frame = None
        self.is_camera_open = False
        # 保存相关
        self.save_dir = self.get_default_save_dir()
        self.image_counter = 1
        # 连续拍摄
        self.continuous_capture = False
        self.capture_timer = QTimer()
        self.capture_timer.timeout.connect(self.capture_single)

        self.init_ui()
        self.log(f"默认保存路径: {self.save_dir}")

    def init_ui(self):
        self.setWindowTitle("相机拍摄工具")
        self.setGeometry(100, 100, 1200, 800)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 上半部分：预览 + 控制
        top_layout = QHBoxLayout()

        # 左侧控制面板
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        control_layout.setAlignment(Qt.AlignTop)

        # 相机控制组
        camera_group = QGroupBox("相机控制")
        camera_layout = QVBoxLayout()
        self.open_camera_btn = QPushButton("打开相机")
        self.open_camera_btn.clicked.connect(self.toggle_camera)
        self.close_camera_btn = QPushButton("关闭相机")
        self.close_camera_btn.clicked.connect(self.close_camera)
        self.close_camera_btn.setEnabled(False)
        camera_layout.addWidget(self.open_camera_btn)
        camera_layout.addWidget(self.close_camera_btn)
        camera_group.setLayout(camera_layout)
        control_layout.addWidget(camera_group)

        # 拍摄控制组
        capture_group = QGroupBox("拍摄控制")
        capture_layout = QVBoxLayout()
        self.single_capture_btn = QPushButton("拍摄单张")
        self.single_capture_btn.clicked.connect(self.capture_single)
        self.single_capture_btn.setEnabled(False)
        self.continuous_capture_btn = QPushButton("开始连续拍摄")
        self.continuous_capture_btn.clicked.connect(self.toggle_continuous_capture)
        self.continuous_capture_btn.setEnabled(False)
        capture_layout.addWidget(self.single_capture_btn)
        capture_layout.addWidget(self.continuous_capture_btn)
        capture_group.setLayout(capture_layout)
        control_layout.addWidget(capture_group)

        # 保存设置组
        save_group = QGroupBox("保存设置")
        save_layout = QVBoxLayout()
        self.save_path_label = QLabel(f"当前路径:\n{self.save_dir}")
        self.save_path_label.setWordWrap(True)
        self.select_path_btn = QPushButton("选择保存路径")
        self.select_path_btn.clicked.connect(self.select_save_path)
        save_layout.addWidget(self.save_path_label)
        save_layout.addWidget(self.select_path_btn)
        save_group.setLayout(save_layout)
        control_layout.addWidget(save_group)

        control_layout.addStretch()
        top_layout.addWidget(control_widget, 1)

        # 右侧预览区域
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(900, 600)
        self.preview_label.setStyleSheet("border:1px solid gray; background:black;")
        self.preview_label.setText("相机预览")
        self.preview_label.setAlignment(Qt.AlignCenter)
        top_layout.addWidget(self.preview_label, 4)

        main_layout.addLayout(top_layout, 4)

        # 底部日志区域
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group, 1)

    # ----------------------------- 辅助函数 -----------------------------
    def log(self, msg):
        time_str = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{time_str}] {msg}")
        print(f"[{time_str}] {msg}")

    def get_default_save_dir(self):
        # 默认保存到桌面的CameraImages文件夹
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        save_dir = os.path.join(desktop, "CameraImages")
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        return save_dir

    def select_save_path(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择保存路径", self.save_dir)
        if dir_path:
            self.save_dir = dir_path
            self.save_path_label.setText(f"当前路径:\n{self.save_dir}")
            self.image_counter = 1  # 重置图片计数器
            self.log(f"保存路径已更改为: {self.save_dir}")

    # ----------------------------- 相机控制 -----------------------------
    def toggle_camera(self):
        if not self.is_camera_open:
            self.open_camera()
        else:
            self.close_camera()

    def open_camera(self):
        if self.is_camera_open:
            return
        # 自动检测 Basler 相机
        use_basler = False
        if BASLER_SUPPORT:
            try:
                devices = pylon.TlFactory.GetInstance().EnumerateDevices()
                use_basler = len(devices) > 0
            except:
                pass
        self.camera_thread = CameraThread(use_basler=use_basler)
        self.camera_thread.frame_signal.connect(self.update_preview)
        self.camera_thread.error_signal.connect(self.log)
        self.camera_thread.start()
        self.is_camera_open = True
        # 更新按钮状态
        self.open_camera_btn.setEnabled(False)
        self.close_camera_btn.setEnabled(True)
        self.single_capture_btn.setEnabled(True)
        self.continuous_capture_btn.setEnabled(True)
        camera_type = "Basler工业相机" if use_basler else "USB相机"
        self.log(f"{camera_type}已打开")

    def close_camera(self):
        if not self.is_camera_open:
            return
        # 先停止连续拍摄
        if self.continuous_capture:
            self.toggle_continuous_capture()
        # 停止相机线程
        if self.camera_thread:
            self.camera_thread.stop()
            self.camera_thread = None
        self.is_camera_open = False
        self.current_frame = None
        self.preview_label.setText("相机预览")
        # 更新按钮状态
        self.open_camera_btn.setEnabled(True)
        self.close_camera_btn.setEnabled(False)
        self.single_capture_btn.setEnabled(False)
        self.continuous_capture_btn.setEnabled(False)
        self.log("相机已关闭")

    def update_preview(self, frame):
        self.current_frame = frame
        # 缩放显示以适应预览窗口
        label_size = self.preview_label.size()
        h, w = frame.shape[:2]
        scale = min(label_size.width() / w, label_size.height() / h)
        new_w, new_h = int(w * scale), int(h * scale)
        display = cv2.resize(frame, (new_w, new_h))
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, new_w, new_h, new_w * 3, QImage.Format_RGB888)
        self.preview_label.setPixmap(QPixmap.fromImage(qimg))

    # ----------------------------- 拍摄功能 -----------------------------
    def capture_single(self):
        if self.current_frame is None:
            self.log("没有可用的图像帧")
            return
        # 生成文件名：年月日_时分秒_序号.png
        time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.save_dir, f"{time_str}_{self.image_counter:04d}.png")
        cv2.imwrite(filename, self.current_frame)
        self.log(f"已保存: {os.path.basename(filename)}")
        self.image_counter += 1

    def toggle_continuous_capture(self):
        if not self.continuous_capture:
            # 开始连续拍摄，间隔1秒
            self.capture_timer.start(1000)
            self.continuous_capture = True
            self.continuous_capture_btn.setText("停止连续拍摄")
            self.log("开始连续拍摄（间隔1秒）")
        else:
            # 停止连续拍摄
            self.capture_timer.stop()
            self.continuous_capture = False
            self.continuous_capture_btn.setText("开始连续拍摄")
            self.log("连续拍摄已停止")

    # ----------------------------- 关闭事件 -----------------------------
    def closeEvent(self, event):
        self.close_camera()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CameraApp()
    window.show()
    sys.exit(app.exec_())