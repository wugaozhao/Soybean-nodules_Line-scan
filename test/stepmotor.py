import sys
import os
import serial
import serial.tools.list_ports
import cv2
import numpy as np
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGroupBox, QLabel, QComboBox,
                             QPushButton, QSlider, QSpinBox, QTextEdit,
                             QFileDialog, QMessageBox, QProgressBar, QGridLayout)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QThread
from PyQt5.QtGui import QImage, QPixmap

# 导入Basler相机库
try:
    from pypylon import pylon

    BASLER_SUPPORT = True
except ImportError:
    BASLER_SUPPORT = False
    print("警告: pypylon库未安装，Basler相机功能不可用")


class CameraThread(QThread):
    """普通USB相机线程，用于实时捕获图像"""
    frame_signal = pyqtSignal(np.ndarray)
    error_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.camera = None
        self.is_running = False
        self.camera_index = 0

    def set_camera_index(self, index):
        self.camera_index = index

    def run(self):
        try:
            # 尝试打开相机
            self.camera = cv2.VideoCapture(self.camera_index)
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1024)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1024)
            self.camera.set(cv2.CAP_PROP_FPS, 30)

            if not self.camera.isOpened():
                self.error_signal.emit("无法打开相机")
                return

            self.is_running = True
            while self.is_running:
                ret, frame = self.camera.read()
                if ret:
                    self.frame_signal.emit(frame)
                else:
                    self.error_signal.emit("读取相机帧失败")
                    break
                self.msleep(33)  # 约30fps

        except Exception as e:
            self.error_signal.emit(f"相机错误: {str(e)}")

    def stop(self):
        self.is_running = False
        if self.camera:
            self.camera.release()
        self.wait()


class BaslerCameraThread(QThread):
    """Basler相机线程，用于实时捕获图像"""
    frame_signal = pyqtSignal(np.ndarray)
    error_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.camera = None
        self.is_running = False
        self.converter = None

    def run(self):
        try:
            # 创建图像格式转换器
            self.converter = pylon.ImageFormatConverter()
            self.converter.OutputPixelFormat = pylon.PixelType_BGR8packed
            self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

            # 创建Basler相机实例
            tl_factory = pylon.TlFactory.GetInstance()
            devices = tl_factory.EnumerateDevices()

            if not devices:
                self.error_signal.emit("未找到Basler相机")
                return

            self.camera = pylon.InstantCamera(tl_factory.CreateDevice(devices[0]))

            # 设置相机参数 - 高分辨率5484x3660
            self.camera.Open()

            # 设置高分辨率
            try:
                self.camera.Width.SetValue(5484)
                self.camera.Height.SetValue(3660)
                print("Basler相机分辨率设置为: 5484x3660")
            except Exception as e:
                print(f"设置5484x3660分辨率失败: {e}")
                # 如果设置失败，尝试使用最大支持的分辨率
                try:
                    width_max = self.camera.Width.Max
                    height_max = self.camera.Height.Max
                    self.camera.Width.SetValue(width_max)
                    self.camera.Height.SetValue(height_max)
                    print(f"使用最大支持分辨率: {width_max}x{height_max}")
                except Exception as e2:
                    print(f"设置最大分辨率失败: {e2}")
                    # 使用默认分辨率
                    self.camera.Width.SetValue(1920)
                    self.camera.Height.SetValue(1080)
                    print("使用默认分辨率: 1920x1080")

            # 降低帧率以适应高分辨率
            self.camera.AcquisitionFrameRateEnable.SetValue(True)
            self.camera.AcquisitionFrameRate.SetValue(10.0)  # 降低到10fps

            # 开始采集
            self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
            self.is_running = True

            while self.is_running and self.camera.IsGrabbing():
                grab_result = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)

                if grab_result.GrabSucceeded():
                    # 转换图像为OpenCV格式
                    image = self.converter.Convert(grab_result)
                    frame = image.GetArray()
                    self.frame_signal.emit(frame)

                grab_result.Release()
                self.msleep(100)  # 降低帧率，约10fps

        except Exception as e:
            self.error_signal.emit(f"Basler相机错误: {str(e)}")
        finally:
            if self.camera:
                self.camera.StopGrabbing()
                self.camera.Close()

    def stop(self):
        self.is_running = False
        if self.camera:
            self.camera.StopGrabbing()
            self.camera.Close()
        self.wait()


class MotorControlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.is_connected = False
        self.current_path = ""
        self.auto_path = ""
        self.image_count = 1
        self.auto_mode = False
        self.camera_thread = None
        self.current_frame = None
        self.current_direction = 1  # 默认前进方向
        self.last_captured_path = ""
        self.auto_capture_pending = False  # 自动采集等待标志
        self.auto_capture_delay = 500  # 自动采集延迟缩短为500ms
        self.waiting_for_movement_complete = False  # 等待移动完成标志

        # 自动采集状态变量
        self.auto_x_steps = 0
        self.auto_z_steps = 0
        self.current_x_step = 0
        self.current_z_step = 0
        self.x_direction = -1  # X轴起始方向：-1表示反向（向左）
        self.z_direction = -1  # Z轴方向：-1表示向下
        self.auto_phase = "x_reverse"  # 当前运动阶段
        self.auto_cycle_count = 0  # 循环计数
        self.auto_capture_count = 0  # 自动采集计数
        self.is_first_capture = True  # 标记是否为第一次采集

        self.init_ui()
        self.scan_serial_ports()
        self.start_camera_preview()

        # 自动采集定时器
        self.auto_capture_timer = QTimer(self)
        self.auto_capture_timer.timeout.connect(self.execute_auto_capture)

    def init_ui(self):
        self.setWindowTitle("根系图像采集助手 - 带实时预览 (Basler: 5484×3660)")
        self.setGeometry(100, 100, 1200, 800)

        # 中央窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QHBoxLayout(central_widget)

        # 左侧控制面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 右侧图像显示面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # 添加各个功能组到左侧面板
        serial_group = self.create_serial_group()
        left_layout.addWidget(serial_group)

        motor_group = self.create_motor_group()
        left_layout.addWidget(motor_group)

        auto_group = self.create_auto_group()
        left_layout.addWidget(auto_group)

        status_group = self.create_status_group()
        left_layout.addWidget(status_group)

        left_layout.addStretch()

        # 添加图像显示组件到右侧面板
        preview_group = self.create_preview_group()
        right_layout.addWidget(preview_group)

        captured_group = self.create_captured_group()
        right_layout.addWidget(captured_group)

        # 设置左右面板比例
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel, 1)

        # 添加串口读取定时器
        self.serial_timer = QTimer(self)
        self.serial_timer.timeout.connect(self.read_serial_data)
        self.serial_timer.start(100)  # 每100ms检查一次串口

    def create_preview_group(self):
        """创建实时预览区域"""
        group = QGroupBox("实时预览")
        layout = QVBoxLayout()

        # 相机选择
        camera_layout = QHBoxLayout()
        camera_layout.addWidget(QLabel("相机选择:"))
        self.camera_combo = QComboBox()
        self.camera_combo.addItems(["相机0"])

        # 如果支持Basler相机，添加选项
        if BASLER_SUPPORT:
            self.camera_combo.addItem("Basler相机 (5484×3660)")

        self.camera_combo.currentIndexChanged.connect(self.change_camera)
        camera_layout.addWidget(self.camera_combo)

        self.preview_btn = QPushButton("开始预览")
        self.preview_btn.clicked.connect(self.toggle_preview)
        camera_layout.addWidget(self.preview_btn)
        layout.addLayout(camera_layout)

        # 预览图像显示
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(500, 400)
        self.preview_label.setStyleSheet("border: 1px solid gray; background-color: black;")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setText("相机未启动")
        layout.addWidget(self.preview_label)

        # 预览信息
        info_layout = QHBoxLayout()
        self.preview_info = QLabel("分辨率: -  FPS: -")
        info_layout.addWidget(self.preview_info)
        info_layout.addStretch()

        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 100)  # 调整缩放范围以适应高分辨率
        self.zoom_slider.setValue(25)  # 默认25%缩放
        self.zoom_slider.valueChanged.connect(self.update_preview_zoom)
        info_layout.addWidget(QLabel("缩放:"))
        info_layout.addWidget(self.zoom_slider)
        layout.addLayout(info_layout)

        group.setLayout(layout)
        return group

    def create_captured_group(self):
        """创建已采集图像显示区域"""
        group = QGroupBox("最近采集的图像")
        layout = QVBoxLayout()

        # 图像显示区域
        self.captured_label = QLabel()
        self.captured_label.setMinimumSize(500, 300)
        self.captured_label.setStyleSheet("border: 1px solid gray; background-color: black;")
        self.captured_label.setAlignment(Qt.AlignCenter)
        self.captured_label.setText("暂无采集图像")
        layout.addWidget(self.captured_label)

        # 图像信息
        info_layout = QHBoxLayout()
        self.captured_info = QLabel("文件名: -  大小: -  时间: -")
        info_layout.addWidget(self.captured_info)

        self.show_original_btn = QPushButton("查看原图")
        self.show_original_btn.clicked.connect(self.show_original_image)
        info_layout.addWidget(self.show_original_btn)
        layout.addLayout(info_layout)

        group.setLayout(layout)
        return group

    def create_serial_group(self):
        group = QGroupBox("串口控制")
        layout = QHBoxLayout()

        # 串口状态指示灯
        self.status_led = QLabel()
        self.status_led.setFixedSize(20, 20)
        self.status_led.setStyleSheet("background-color: gray; border-radius: 10px;")
        layout.addWidget(self.status_led)

        layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(100)
        layout.addWidget(self.port_combo)

        layout.addWidget(QLabel("波特率:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "115200", "57600", "38400", "19200"])
        self.baud_combo.setCurrentText("9600")
        layout.addWidget(self.baud_combo)

        self.refresh_btn = QPushButton("刷新串口")
        self.refresh_btn.clicked.connect(self.scan_serial_ports)
        layout.addWidget(self.refresh_btn)

        self.connect_btn = QPushButton("打开串口")
        self.connect_btn.clicked.connect(self.toggle_serial_connection)
        layout.addWidget(self.connect_btn)

        # 测试按钮
        self.test_btn = QPushButton("测试通信")
        self.test_btn.clicked.connect(self.test_serial_connection)
        layout.addWidget(self.test_btn)

        layout.addStretch()
        group.setLayout(layout)
        return group

    def create_motor_group(self):
        group = QGroupBox("电机控制")
        layout = QVBoxLayout()

        motor_select_layout = QHBoxLayout()
        motor_select_layout.addWidget(QLabel("电机选择:"))
        self.motor_combo = QComboBox()
        self.motor_combo.addItems(["X", "Y", "Z", "A"])
        motor_select_layout.addWidget(self.motor_combo)
        motor_select_layout.addStretch()
        layout.addLayout(motor_select_layout)

        direction_layout = QHBoxLayout()
        direction_layout.addWidget(QLabel("方向:"))
        self.forward_btn = QPushButton("前进")
        self.forward_btn.clicked.connect(lambda: self.set_direction(1))
        direction_layout.addWidget(self.forward_btn)

        self.backward_btn = QPushButton("后退")
        self.backward_btn.clicked.connect(lambda: self.set_direction(0))
        direction_layout.addWidget(self.backward_btn)

        self.direction_label = QLabel("未选择")
        direction_layout.addWidget(self.direction_label)
        layout.addLayout(direction_layout)

        pulse_layout = QHBoxLayout()
        pulse_layout.addWidget(QLabel("脉冲数:"))
        self.pulse_spin = QSpinBox()
        self.pulse_spin.setRange(1, 20000)
        self.pulse_spin.setValue(1000)
        pulse_layout.addWidget(self.pulse_spin)

        self.send_pulse_btn = QPushButton("发送脉冲")
        self.send_pulse_btn.clicked.connect(self.send_pulse)
        pulse_layout.addWidget(self.send_pulse_btn)
        layout.addLayout(pulse_layout)

        group.setLayout(layout)
        return group

    def create_auto_group(self):
        group = QGroupBox("自动图像采集 (X-Z交替运动)")
        layout = QVBoxLayout()

        auto_path_layout = QHBoxLayout()
        self.auto_path_label = QLabel("未选择路径")
        auto_path_layout.addWidget(self.auto_path_label)

        self.auto_select_path_btn = QPushButton("选择路径")
        self.auto_select_path_btn.clicked.connect(self.select_auto_path)
        auto_path_layout.addWidget(self.auto_select_path_btn)
        layout.addLayout(auto_path_layout)

        param_layout = QGridLayout()
        param_layout.addWidget(QLabel("X轴步数:"), 0, 0)
        self.x_steps_spin = QSpinBox()
        self.x_steps_spin.setRange(1, 100)
        self.x_steps_spin.setValue(5)
        param_layout.addWidget(self.x_steps_spin, 0, 1)

        param_layout.addWidget(QLabel("Z轴步数:"), 1, 0)
        self.z_steps_spin = QSpinBox()
        self.z_steps_spin.setRange(1, 100)
        self.z_steps_spin.setValue(2)
        param_layout.addWidget(self.z_steps_spin, 1, 1)

        param_layout.addWidget(QLabel("步长(mm):"), 0, 2)
        self.step_size_spin = QSpinBox()
        self.step_size_spin.setRange(1, 100)
        self.step_size_spin.setValue(1)
        param_layout.addWidget(self.step_size_spin, 0, 3)

        # 添加分辨率信息
        param_layout.addWidget(QLabel("Basler分辨率:"), 1, 2)
        resolution_label = QLabel("5484×3660")
        param_layout.addWidget(resolution_label, 1, 3)

        layout.addLayout(param_layout)

        self.auto_capture_btn = QPushButton("开始自动采集")
        self.auto_capture_btn.clicked.connect(self.toggle_auto_capture)
        layout.addWidget(self.auto_capture_btn)

        group.setLayout(layout)
        return group

    def create_status_group(self):
        group = QGroupBox("状态信息")
        layout = QVBoxLayout()

        self.status_text = QTextEdit()
        self.status_text.setMaximumHeight(150)
        self.status_text.setReadOnly(True)
        layout.addWidget(self.status_text)

        group.setLayout(layout)
        return group

    def start_camera_preview(self):
        """启动相机预览"""
        if self.camera_thread:
            self.stop_camera_preview()

        # 获取当前选择的相机类型
        camera_index = self.camera_combo.currentIndex()
        camera_text = self.camera_combo.currentText()

        # 如果是Basler相机且支持
        if "Basler相机" in camera_text and BASLER_SUPPORT:
            self.camera_thread = BaslerCameraThread()
            self.show_message("信息", "启动Basler相机预览 (分辨率: 5484×3660)")
        else:
            self.camera_thread = CameraThread()
            self.camera_thread.set_camera_index(camera_index)
            self.show_message("信息", "启动USB相机预览")

        self.camera_thread.frame_signal.connect(self.update_preview)
        self.camera_thread.error_signal.connect(self.camera_error)
        self.camera_thread.start()
        self.preview_btn.setText("停止预览")

    def stop_camera_preview(self):
        """停止相机预览"""
        if self.camera_thread:
            self.camera_thread.stop()
            self.camera_thread = None
        self.preview_label.setText("预览已停止")
        self.preview_btn.setText("开始预览")

    def toggle_preview(self):
        """切换预览状态"""
        if self.camera_thread and self.camera_thread.is_running:
            self.stop_camera_preview()
        else:
            self.start_camera_preview()

    def change_camera(self, index):
        """切换相机"""
        # 如果预览正在运行，先停止再重新启动
        if self.camera_thread and self.camera_thread.is_running:
            self.stop_camera_preview()
            self.start_camera_preview()

    def update_preview(self, frame):
        """更新预览图像"""
        self.current_frame = frame

        # 缩放图像以适应显示
        zoom_factor = self.zoom_slider.value() / 100.0
        height, width = frame.shape[:2]

        # 计算缩放后的尺寸
        new_width = int(width * zoom_factor)
        new_height = int(height * zoom_factor)

        # 调整尺寸以适应显示区域
        max_display_width = self.preview_label.width()
        max_display_height = self.preview_label.height()

        if new_width > max_display_width or new_height > max_display_height:
            # 如果缩放后仍然太大，进一步缩放以适应显示区域
            width_ratio = max_display_width / new_width
            height_ratio = max_display_height / new_height
            scale_ratio = min(width_ratio, height_ratio)
            new_width = int(new_width * scale_ratio)
            new_height = int(new_height * scale_ratio)

        resized_frame = cv2.resize(frame, (new_width, new_height))

        # 转换为QImage并显示
        rgb_image = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)

        self.preview_label.setPixmap(QPixmap.fromImage(qt_image))

        # 更新预览信息
        self.preview_info.setText(f"分辨率: {width}x{height} 缩放: {zoom_factor:.1%} 显示: {new_width}x{new_height}")

    def update_preview_zoom(self, value):
        """更新预览缩放"""
        if self.current_frame is not None:
            self.update_preview(self.current_frame)

    def save_image(self, frame, prefix="image", x_index=None, z_index=None):
        """保存图像并更新显示"""
        if not self.current_path:
            self.show_message("错误", "请先选择保存路径")
            return False

        try:
            # 创建保存目录
            img_dir = os.path.join(self.current_path, "IMG")
            os.makedirs(img_dir, exist_ok=True)

            # 生成文件名 - 移除坐标信息，仅使用序号
            if x_index is not None and z_index is not None:
                # 自动采集模式
                filename = f"{prefix}_{self.auto_capture_count:04d}.png"
            else:
                # 手动采集模式
                filename = f"{prefix}_{self.image_count:04d}.png"

            filepath = os.path.join(img_dir, filename)

            # 保存图像（高质量）
            cv2.imwrite(filepath, frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])

            # 获取实际保存的图像信息
            saved_image = cv2.imread(filepath)
            if saved_image is not None:
                height, width = saved_image.shape[:2]
                self.show_message("信息", f"图像已保存: {filename} (分辨率: {width}x{height})")
            else:
                self.show_message("信息", f"图像已保存: {filename}")

            # 更新采集图像显示（使用缩略图）
            self.display_captured_image(frame, filename, filepath)

            # 更新计数器
            if x_index is not None and z_index is not None:
                self.auto_capture_count += 1
            else:
                self.image_count += 1

            return True

        except Exception as e:
            self.show_message("错误", f"保存图像失败: {str(e)}")
            return False

    def display_captured_image(self, frame, filename, filepath):
        """显示最近采集的图像"""
        # 缩放图像以适应显示
        height, width = frame.shape[:2]
        display_height = 300
        scale_factor = display_height / height
        display_width = int(width * scale_factor)

        resized_frame = cv2.resize(frame, (display_width, display_height))

        # 转换为QImage并显示
        rgb_image = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)

        self.captured_label.setPixmap(QPixmap.fromImage(qt_image))

        # 更新图像信息
        file_size = os.path.getsize(filepath) / 1024  # KB
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.captured_info.setText(
            f"文件名: {filename}  大小: {file_size:.1f}KB  时间: {timestamp}  分辨率: {width}x{height}")

        # 保存最近图像路径用于查看原图
        self.last_captured_path = filepath

    def show_original_image(self):
        """查看原图"""
        if hasattr(self, 'last_captured_path') and os.path.exists(self.last_captured_path):
            # 使用系统默认程序打开图像
            if sys.platform == "win32":
                os.startfile(self.last_captured_path)
            elif sys.platform == "darwin":  # macOS
                os.system(f"open '{self.last_captured_path}'")
            else:  # Linux
                os.system(f"xdg-open '{self.last_captured_path}'")
        else:
            self.show_message("错误", "没有可用的图像文件")

    def camera_error(self, error_msg):
        """相机错误处理"""
        self.show_message("相机错误", error_msg)
        self.preview_label.setText("相机错误")

    def scan_serial_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)

        if not ports:
            self.port_combo.addItem("未找到串口")

    def test_serial_connection(self):
        """测试串口通信"""
        if not self.is_connected:
            self.show_message("错误", "请先打开串口")
            return

        # 发送测试命令
        command = "X1000"
        if self.send_serial_command(command):
            self.show_message("测试", f"已发送测试命令: {command}")

    def toggle_serial_connection(self):
        if not self.is_connected:
            self.connect_serial()
        else:
            self.disconnect_serial()

    def connect_serial(self):
        if self.port_combo.currentText() == "未找到串口":
            self.show_message("错误", "没有可用的串口")
            return

        try:
            port = self.port_combo.currentText()
            baudrate = int(self.baud_combo.currentText())

            self.serial_port = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1,
                xonxoff=False,  # 禁用软件流控制
                rtscts=False,  # 禁用硬件(RTS/CTS)流控制
                dsrdtr=False  # 禁用硬件(DSR/DTR)流控制
            )

            # 等待Arduino重启
            time.sleep(2)

            # 刷新输入输出缓冲区
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()

            self.is_connected = True
            self.connect_btn.setText("关闭串口")
            self.status_led.setStyleSheet("background-color: green; border-radius: 10px;")
            self.show_message("信息", f"成功连接到串口 {port}")

            # 发送初始命令测试
            self.send_serial_command("STATUS")

        except Exception as e:
            self.status_led.setStyleSheet("background-color: red; border-radius: 10px;")
            self.show_message("错误", f"连接串口失败: {str(e)}")

    def disconnect_serial(self):
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()

        self.is_connected = False
        self.connect_btn.setText("打开串口")
        self.status_led.setStyleSheet("background-color: gray; border-radius: 10px;")
        self.show_message("信息", "已断开串口连接")

    def send_serial_command(self, command):
        """发送命令到Arduino"""
        if self.is_connected and self.serial_port and self.serial_port.is_open:
            try:
                # 确保命令以换行符结束
                full_command = command + '\n'
                self.serial_port.write(full_command.encode())

                # 立即刷新输出缓冲区
                self.serial_port.flush()

                self.show_message("发送", command)
                return True
            except Exception as e:
                self.status_led.setStyleSheet("background-color: red; border-radius: 10px;")
                self.show_message("错误", f"发送命令失败: {str(e)}")
                return False
        else:
            self.show_message("错误", "串口未连接")
            return False

    def set_direction(self, direction):
        """设置电机方向"""
        self.current_direction = direction
        direction_text = "前进" if direction == 1 else "后退"
        self.direction_label.setText(direction_text)

        motor = self.motor_combo.currentText()
        command = f"DIR {motor} {direction}"
        self.send_serial_command(command)

    def send_pulse(self):
        """发送脉冲命令"""
        if not hasattr(self, 'current_direction'):
            self.show_message("警告", "请先选择方向")
            return

        pulses = self.pulse_spin.value()
        motor = self.motor_combo.currentText()  # 获取选择的电机轴

        # 根据方向添加符号
        sign = "" if self.current_direction == 1 else "-"
        command = f"{motor}{sign}{pulses}"

        if self.send_serial_command(command):
            self.show_message("信息", f"已发送 {pulses} 个脉冲到{self.motor_combo.currentText()}")

    def select_auto_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择自动采集保存路径")
        if path:
            self.auto_path = path
            self.auto_path_label.setText(os.path.basename(path))
            # 设置自动采集的保存路径
            self.current_path = path

            # 初始化图像计数
            img_path = os.path.join(path, "IMG")
            if os.path.exists(img_path):
                images = [f for f in os.listdir(img_path) if f.endswith('.png')]
                self.image_count = len(images) + 1

                # 查找最大的自动采集计数
                auto_images = [f for f in images if f.startswith('auto_capture')]
                if auto_images:
                    max_count = 0
                    for img in auto_images:
                        try:
                            # 解析文件名：auto_capture_0001.png -> 0001
                            parts = img.split('_')
                            if len(parts) >= 3:
                                # 提取序号部分并移除扩展名
                                count_str = parts[2].split('.')[0]
                                count = int(count_str)
                                max_count = max(max_count, count)
                        except:
                            continue
                    self.auto_capture_count = max_count + 1
                else:
                    self.auto_capture_count = 1
            else:
                self.image_count = 1
                self.auto_capture_count = 1

    def capture_high_resolution_image(self, x_index=None, z_index=None):
        """采集高分辨率图像 - 使用预览帧进行采集"""
        if not self.current_path:
            self.show_message("错误", "请先选择保存路径")
            return False

        try:
            camera_text = self.camera_combo.currentText()

            if "Basler相机" in camera_text and BASLER_SUPPORT:
                # 对于Basler相机，直接使用预览帧进行采集
                if self.camera_thread and self.camera_thread.is_running:
                    if self.current_frame is not None:
                        success = self.save_image(self.current_frame, "auto_capture", x_index, z_index)
                        return success
                    else:
                        self.show_message("错误", "没有可用的预览图像")
                        return False
                else:
                    self.show_message("错误", "Basler相机预览未运行")
                    return False
            else:
                # 使用普通USB相机
                if self.camera_thread and self.camera_thread.is_running:
                    if self.current_frame is not None:
                        success = self.save_image(self.current_frame, "auto_capture", x_index, z_index)
                        return success
                    else:
                        self.show_message("错误", "没有可用的预览图像")
                        return False
                else:
                    # 对于其他情况，使用独立实例
                    cap = cv2.VideoCapture(0)
                    if not cap.isOpened():
                        cap = cv2.VideoCapture(1)

                    if not cap.isOpened():
                        self.show_message("错误", "无法打开采集相机")
                        return False

                    ret, frame = cap.read()
                    if ret:
                        success = self.save_image(frame, "auto_capture", x_index, z_index)
                        cap.release()
                        return success
                    else:
                        self.show_message("错误", "无法读取相机图像")
                        cap.release()
                        return False

        except Exception as e:
            self.show_message("错误", f"采集图像失败: {str(e)}")
            return False

    def toggle_auto_capture(self):
        if not self.auto_mode:
            self.start_auto_capture()
        else:
            self.stop_auto_capture()

    def start_auto_capture(self):
        """开始自动采集 - 使用下位机的AUTO命令"""
        if not hasattr(self, 'auto_path') or not self.auto_path:
            self.show_message("错误", "请先选择自动采集保存路径")
            return

        # 获取参数
        x_steps = self.x_steps_spin.value()  # X轴步数
        z_steps = self.z_steps_spin.value()  # Z轴步数
        step_size = self.step_size_spin.value()  # 步长(mm)

        # 计算总脉冲数（1mm = 330脉冲）
        step_pulses = step_size * 330

        # 初始化自动采集状态
        self.auto_x_steps = x_steps
        self.auto_z_steps = z_steps
        self.current_x_step = 0
        self.current_z_step = 0
        self.x_direction = -1  # 起始方向为反向
        self.auto_phase = "x_reverse"
        self.auto_cycle_count = 0
        self.auto_capture_count = 0
        self.is_first_capture = True  # 重置为第一次采集

        # 发送AUTO命令到下位机
        command = f"AUTO {x_steps} {z_steps} {step_pulses}"
        if self.send_serial_command(command):
            self.auto_mode = True
            self.auto_capture_btn.setText("停止自动采集")
            camera_text = self.camera_combo.currentText()
            if "Basler相机" in camera_text:
                self.show_message("信息", f"开始自动采集: X轴{x_steps}步, Z轴{z_steps}步, 步长{step_size}mm")
                self.show_message("信息", "Basler相机采集分辨率: 5484×3660")
            else:
                self.show_message("信息", f"开始自动采集: X轴{x_steps}步, Z轴{z_steps}步, 步长{step_size}mm")
            self.show_message("信息", "运动模式: X轴反向→Z轴向下→X轴正向→Z轴向下，循环")

            # 开始自动采集时立即拍摄第一张图像（起始位置）
            self.show_message("信息", "开始采集起始位置图像...")
            success = self.capture_high_resolution_image(self.current_x_step, self.current_z_step)
            if success:
                self.show_message("信息", f"起始位置图像采集完成 (X={self.current_x_step}, Z={self.current_z_step})")
                self.is_first_capture = False  # 第一次采集完成
            else:
                self.show_message("错误", "起始位置图像采集失败")
                self.stop_auto_capture()
        else:
            self.show_message("错误", "启动自动采集失败")

    def stop_auto_capture(self):
        """停止自动采集"""
        if self.send_serial_command("STOP"):
            self.auto_mode = False
            self.auto_capture_btn.setText("开始自动采集")
            self.show_message("信息", "已发送停止命令")

    def execute_auto_capture(self):
        """执行自动采集（定时器回调）"""
        if self.auto_capture_pending and self.auto_mode:
            self.auto_capture_timer.stop()  # 停止定时器
            self.auto_capture_pending = False

            # 执行图像采集，使用当前坐标信息
            success = self.capture_high_resolution_image(self.current_x_step, self.current_z_step)

            if not success:
                # 采集失败，停止自动采集
                self.show_message("错误", "图像采集失败，停止自动采集")
                self.stop_auto_capture()
            else:
                # 采集成功后更新坐标信息用于下一次采集
                # 注意：这里不更新坐标，坐标更新由下位机控制
                pass

    def read_serial_data(self):
        """读取串口数据"""
        if self.is_connected and self.serial_port and self.serial_port.in_waiting > 0:
            try:
                data = self.serial_port.readline().decode().strip()
                if data:
                    self.process_serial_data(data)
            except Exception as e:
                self.show_message("错误", f"读取串口数据失败: {str(e)}")

    def process_serial_data(self, data):
        """处理从Arduino接收的数据"""
        self.show_message("接收", data)

        # 处理移动完成信号
        if data == "MOVEMENT_COMPLETE":
            self.show_message("信息", "电机移动完成")
            self.waiting_for_movement_complete = False

        # 处理拍照触发信号
        elif data == "CAPTURE_TRIGGER":
            self.show_message("自动采集",
                              f"位置到达，准备采集图像... (X={self.current_x_step}, Z={self.current_z_step})")
            # 设置采集标志并启动采集定时器
            self.auto_capture_pending = True
            self.auto_capture_timer.start(self.auto_capture_delay)

        # 处理位置更新信号
        elif data.startswith("POSITION:"):
            # 解析位置信息，格式：POSITION:X1,Z2
            try:
                parts = data.split(":")
                if len(parts) == 2:
                    coords = parts[1].split(",")
                    if len(coords) == 2:
                        x_part = coords[0]
                        z_part = coords[1]
                        if x_part.startswith("X") and z_part.startswith("Z"):
                            self.current_x_step = int(x_part[1:])
                            self.current_z_step = int(z_part[1:])
                            self.show_message("坐标信息", f"位置更新: X={self.current_x_step}, Z={self.current_z_step}")
            except Exception as e:
                self.show_message("错误", f"解析位置信息失败: {e}")

        # 处理自动模式开始
        elif data.startswith("AUTO_MODE_START:"):
            self.show_message("信息", "自动采集已开始")

        # 处理自动模式完成
        elif data == "AUTO_MODE_COMPLETE":
            self.show_message("信息", "自动采集完成")
            self.auto_mode = False
            self.auto_capture_btn.setText("开始自动采集")

        # 处理自动模式停止
        elif data == "AUTO_MODE_STOPPED":
            self.show_message("信息", "自动采集已停止")
            self.auto_mode = False
            self.auto_capture_btn.setText("开始自动采集")

    def show_message(self, title, message):
        self.status_text.append(f"[{title}] {message}")
        # 自动滚动到底部
        scrollbar = self.status_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        """关闭程序时的清理工作"""
        if self.camera_thread:
            self.camera_thread.stop()
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        if self.auto_capture_timer.isActive():
            self.auto_capture_timer.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MotorControlGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()