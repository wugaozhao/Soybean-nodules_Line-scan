import sys
import os
import serial
import serial.tools.list_ports
import cv2
import numpy as np
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGroupBox, QLabel, QComboBox,
                             QPushButton, QTextEdit, QRadioButton, QButtonGroup)
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

# ----------------------------- 相机线程（支持USB和Basler） -----------------------------
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
                # 设置参数
                try:
                    self.camera.ExposureTime.SetValue(35000)      # 曝光时间 35000 µs
                    self.camera.BalanceWhiteAuto.SetValue("Once") # 白平衡 once
                except Exception as e:
                    print(f"相机参数设置失败: {e}")
                # 设置分辨率（可选）
                try:
                    self.camera.Width.SetValue(1920)
                    self.camera.Height.SetValue(1080)
                except:
                    pass
                self.camera.AcquisitionFrameRateEnable.SetValue(True)
                self.camera.AcquisitionFrameRate.SetValue(10)
                self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
                self.is_running = True
                while self.is_running and self.camera.IsGrabbing():
                    grab_result = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
                    if grab_result.GrabSucceeded():
                        image = self.converter.Convert(grab_result)
                        frame = image.GetArray()
                        self.frame_signal.emit(frame)
                    grab_result.Release()
                    self.msleep(33)  # ~30fps
            else:
                # USB 相机（OpenCV）
                self.camera = cv2.VideoCapture(0)
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.camera.set(cv2.CAP_PROP_FPS, 30)
                # USB 相机尝试设置曝光和白平衡（可能无效）
                self.camera.set(cv2.CAP_PROP_EXPOSURE, 35000 / 1000)  # 有些相机需要毫秒
                # 白平衡需要具体API，这里略
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
                    self.msleep(33)
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
        if self.camera and not self.use_basler:
            self.camera.release()
        self.wait()

# ----------------------------- 主窗口 -----------------------------
class MotorControlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        # 串口相关
        self.serial_port = None
        self.is_connected = False
        # 相机线程
        self.camera_thread = None
        self.current_frame = None
        # 运动控制状态
        self.is_running = False          # 启动/停止标志
        self.state = "IDLE"              # IDLE, MOVING_Y, MOVING_Z
        self.y_direction = 1             # 1: 正向, -1: 反向 (初始值由用户设置)
        self.z_direction = 1             # 1: 正向, -1: 反向
        self.z_total_pulses = 0          # 已走的Z轴累计脉冲
        self.z_target = 500000           # Z轴目标总脉冲数
        self.y_step = 66500              # Y轴每次移动脉冲数
        self.z_step = 16000              # Z轴每次步进脉冲数
        self.image_counter = 1           # 图片序号
        self.save_dir = ""               # 保存目录
        # 定时拍照 (0.3s)
        self.capture_timer = QTimer()
        self.capture_timer.timeout.connect(self.capture_image)

        self.init_ui()
        self.scan_serial_ports()
        self.create_save_directory()

    def init_ui(self):
        self.setWindowTitle("步进电机扫描控制系统")
        self.setGeometry(100, 100, 1200, 800)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 左侧 2/3 预览区域
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(800, 600)
        self.preview_label.setStyleSheet("border:1px solid gray; background:black;")
        self.preview_label.setText("相机预览")
        preview_layout.addWidget(self.preview_label)
        main_layout.addWidget(preview_widget, 2)

        # 右侧 1/3 控制面板
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)

        # 1. 串口连接区域
        serial_group = QGroupBox("串口连接")
        serial_layout = QHBoxLayout()
        self.serial_status_led = QLabel()
        self.serial_status_led.setFixedSize(20, 20)
        self.serial_status_led.setStyleSheet("background:gray;border-radius:10px")
        serial_layout.addWidget(self.serial_status_led)
        serial_layout.addWidget(QLabel("端口:"))
        self.port_combo = QComboBox()
        serial_layout.addWidget(self.port_combo)
        serial_layout.addWidget(QLabel("波特率:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "115200"])
        self.baud_combo.setCurrentText("9600")
        serial_layout.addWidget(self.baud_combo)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.scan_serial_ports)
        serial_layout.addWidget(self.refresh_btn)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_serial)
        serial_layout.addWidget(self.connect_btn)
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.clicked.connect(self.disconnect_serial)
        serial_layout.addWidget(self.disconnect_btn)
        serial_group.setLayout(serial_layout)
        control_layout.addWidget(serial_group)

        # 2. 启停控制区域（可设置Y/Z轴方向）
        motion_group = QGroupBox("启停控制")
        motion_layout = QVBoxLayout()
        # Y轴方向选择
        y_dir_layout = QHBoxLayout()
        y_dir_layout.addWidget(QLabel("Y轴初始方向:"))
        self.y_forward_radio = QRadioButton("正向")
        self.y_backward_radio = QRadioButton("反向")
        self.y_forward_radio.setChecked(True)   # 默认正向
        y_dir_layout.addWidget(self.y_forward_radio)
        y_dir_layout.addWidget(self.y_backward_radio)
        motion_layout.addLayout(y_dir_layout)
        # Z轴方向选择
        z_dir_layout = QHBoxLayout()
        z_dir_layout.addWidget(QLabel("Z轴步进方向:"))
        self.z_forward_radio = QRadioButton("正向")
        self.z_backward_radio = QRadioButton("反向")
        self.z_forward_radio.setChecked(True)   # 默认正向
        z_dir_layout.addWidget(self.z_forward_radio)
        z_dir_layout.addWidget(self.z_backward_radio)
        motion_layout.addLayout(z_dir_layout)
        # 启动/停止按钮
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("启动扫描")
        self.stop_btn = QPushButton("停止扫描")
        self.start_btn.clicked.connect(self.start_scan)
        self.stop_btn.clicked.connect(self.stop_scan)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        motion_layout.addLayout(btn_layout)
        motion_group.setLayout(motion_layout)
        control_layout.addWidget(motion_group)

        # 3. 日志区域
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(200)
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        control_layout.addWidget(log_group)

        control_layout.addStretch()
        main_layout.addWidget(control_widget, 1)

        # 串口读取定时器
        self.serial_timer = QTimer()
        self.serial_timer.timeout.connect(self.read_serial)
        self.serial_timer.start(50)

    # ----------------------------- 辅助函数 -----------------------------
    def log(self, msg):
        self.log_text.append(msg)
        print(msg)

    def scan_serial_ports(self):
        self.port_combo.clear()
        for p in serial.tools.list_ports.comports():
            self.port_combo.addItem(p.device)

    def toggle_serial(self):
        if not self.is_connected:
            try:
                self.serial_port = serial.Serial(
                    self.port_combo.currentText(),
                    int(self.baud_combo.currentText()),
                    timeout=0.1
                )
                self.is_connected = True
                self.serial_status_led.setStyleSheet("background:green;border-radius:10px")
                self.log("串口已连接")
            except Exception as e:
                self.log(f"连接失败: {e}")
        else:
            self.log("串口已经连接，请先断开")

    def disconnect_serial(self):
        if self.is_connected:
            self.serial_port.close()
            self.is_connected = False
            self.serial_status_led.setStyleSheet("background:gray;border-radius:10px")
            self.log("串口已断开")

    def send_command(self, cmd):
        if self.is_connected:
            self.serial_port.write((cmd + "\n").encode())
            self.log(f"发送: {cmd}")
        else:
            self.log("串口未连接，命令未发送")

    def read_serial(self):
        if self.is_connected and self.serial_port:
            try:
                while self.serial_port.in_waiting:
                    line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        self.log(f"← {line}")
                        if line == "OK":
                            self.on_motion_complete()
            except:
                pass

    def create_save_directory(self):
        # 在 D 盘创建当天日期文件夹
        today = datetime.now().strftime("Date%m%d")  # 例如 Date0511
        self.save_dir = os.path.join("D:", today)
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
        self.log(f"图片保存目录: {self.save_dir}")

    def start_camera(self):
        if self.camera_thread and self.camera_thread.is_running:
            return
        # 自动检测 Basler 相机
        use_basler = BASLER_SUPPORT and len(pylon.TlFactory.GetInstance().EnumerateDevices()) > 0
        self.camera_thread = CameraThread(use_basler=use_basler)
        self.camera_thread.frame_signal.connect(self.update_preview)
        self.camera_thread.error_signal.connect(self.log)
        self.camera_thread.start()
        self.log("相机已启动")

    def stop_camera(self):
        if self.camera_thread and self.camera_thread.is_running:
            self.camera_thread.stop()
            self.camera_thread = None
            self.log("相机已停止")

    def update_preview(self, frame):
        self.current_frame = frame
        # 缩放显示
        display = cv2.resize(frame, (800, 600))
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self.preview_label.setPixmap(QPixmap.fromImage(qimg))

    def capture_image(self):
        if self.current_frame is not None:
            filename = os.path.join(self.save_dir, f"img_{self.image_counter:06d}.png")
            cv2.imwrite(filename, self.current_frame)
            self.log(f"已保存: {filename}")
            self.image_counter += 1

    # ----------------------------- 运动控制逻辑 -----------------------------
    def start_scan(self):
        if self.is_running:
            self.log("扫描已在运行中")
            return
        if not self.is_connected:
            self.log("请先连接串口")
            return
        # 获取方向设置
        self.y_direction = 1 if self.y_forward_radio.isChecked() else -1
        self.z_direction = 1 if self.z_forward_radio.isChecked() else -1
        self.z_total_pulses = 0
        self.image_counter = 1
        self.is_running = True
        self.state = "IDLE"
        # 启动相机（如果未启动）
        if self.camera_thread is None:
            self.start_camera()
        # 开始拍照定时器（0.3秒间隔）
        self.capture_timer.start(300)
        # 开始第一个 Y 轴运动
        self.start_y_move()
        self.log("扫描已启动")

    def stop_scan(self):
        if not self.is_running:
            return
        self.is_running = False
        self.capture_timer.stop()
        self.send_command("STOP")
        self.state = "IDLE"
        self.log("扫描已停止")

    def start_y_move(self):
        if not self.is_running:
            return
        pulses = self.y_step * self.y_direction
        self.send_command(f"Y{pulses}")
        self.state = "MOVING_Y"
        self.log(f"Y轴移动 {abs(pulses)} 脉冲，方向={'正向' if self.y_direction==1 else '反向'}")

    def start_z_move(self):
        if not self.is_running:
            return
        pulses = self.z_step * self.z_direction
        self.send_command(f"Z{pulses}")
        self.state = "MOVING_Z"
        self.log(f"Z轴步进 {abs(pulses)} 脉冲，方向={'正向' if self.z_direction==1 else '反向'}")

    def on_motion_complete(self):
        if not self.is_running:
            return
        if self.state == "MOVING_Y":
            # Y 轴完成，检查是否需要继续 Z
            if self.z_total_pulses >= self.z_target:
                self.log("Z 轴总脉冲已达目标，扫描完成")
                self.stop_scan()
                return
            # 开始 Z 步进
            self.start_z_move()
        elif self.state == "MOVING_Z":
            # Z 步进完成，更新累计脉冲
            self.z_total_pulses += self.z_step
            self.log(f"Z累计脉冲: {self.z_total_pulses}/{self.z_target}")
            if self.z_total_pulses >= self.z_target:
                self.log("扫描完成")
                self.stop_scan()
                return
            # Y 轴方向反转
            self.y_direction = -self.y_direction
            self.start_y_move()

    # ----------------------------- 关闭事件 -----------------------------
    def closeEvent(self, event):
        self.stop_scan()
        self.stop_camera()
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MotorControlGUI()
    window.show()
    sys.exit(app.exec_())