import sys
import os
import serial
import serial.tools.list_ports
import cv2
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGroupBox, QLabel, QComboBox,
                             QPushButton, QSpinBox, QTextEdit,
                             QFileDialog, QGridLayout)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QThread
from PyQt5.QtGui import QImage, QPixmap
import warnings
warnings.filterwarnings("ignore")

try:
    from pypylon import pylon
    BASLER_SUPPORT = True
except ImportError:
    BASLER_SUPPORT = False
    print("pypylon 未安装，Basler相机不可用")

# ---------- 相机线程 ----------
class CameraThread(QThread):
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
                self.msleep(33)
        except Exception as e:
            self.error_signal.emit(f"相机错误: {str(e)}")
    def stop(self):
        self.is_running = False
        if self.camera:
            self.camera.release()
        self.wait()

class BaslerCameraThread(QThread):
    frame_signal = pyqtSignal(np.ndarray)
    error_signal = pyqtSignal(str)
    def __init__(self):
        super().__init__()
        self.camera = None
        self.is_running = False
        self.converter = None
    def run(self):
        try:
            from pypylon import pylon
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
            try:
                self.camera.Width.SetValue(5472)
                self.camera.Height.SetValue(3648)
            except:
                self.camera.Width.SetValue(1920)
                self.camera.Height.SetValue(1080)
            self.camera.AcquisitionFrameRateEnable.SetValue(True)
            self.camera.AcquisitionFrameRate.SetValue(10.0)
            self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
            self.is_running = True
            while self.is_running and self.camera.IsGrabbing():
                grab_result = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
                if grab_result.GrabSucceeded():
                    image = self.converter.Convert(grab_result)
                    frame = image.GetArray()
                    self.frame_signal.emit(frame)
                grab_result.Release()
                self.msleep(100)
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

def is_basler_camera_connected():
    if not BASLER_SUPPORT:
        return False
    try:
        from pypylon import pylon
        tlf = pylon.TlFactory.GetInstance()
        devs = tlf.EnumerateDevices()
        return len(devs) > 0
    except:
        return False

# ---------- 主窗口 ----------
class MotorControlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        # 电机串口
        self.serial_port = None
        self.is_connected = False
        # 小车串口
        self.car_serial_port = None
        self.car_is_connected = False

        self.current_path = ""
        self.image_count = 1
        self.camera_thread = None
        self.current_frame = None

        # 自动模式相关
        self.auto_mode = False
        self.auto_state = "IDLE"      # IDLE, MOVING_Y, MOVING_Z
        self.y_direction = 1           # 1: 正向, -1: 反向
        self.current_row = 0
        self.y_total_pulses = 0
        self.z_step_pulses = 0
        self.total_rows = 0
        self.capture_interval = 300
        self.capture_timer = QTimer()
        self.capture_timer.timeout.connect(self.capture_once)

        self.init_ui()
        self.scan_serial_ports()
        self.scan_car_serial_ports()

    def init_ui(self):
        self.setWindowTitle("蛇形扫描 + 连续飞拍系统 + 小车控制")
        self.setGeometry(100, 100, 1300, 800)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        left_layout.addWidget(self.create_serial_group())       # 电机串口（含断开按钮）
        left_layout.addWidget(self.create_car_group())          # 小车控制（含断开按钮）
        left_layout.addWidget(self.create_motor_group())
        left_layout.addWidget(self.create_auto_group())
        left_layout.addWidget(self.create_status_group())
        left_layout.addStretch()

        right_layout.addWidget(self.create_preview_group())
        right_layout.addWidget(self.create_captured_group())

        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel, 1)

        # 串口读取定时器（电机）
        self.serial_timer = QTimer()
        self.serial_timer.timeout.connect(self.read_serial_data)
        self.serial_timer.start(50)

        # 小车串口读取定时器
        self.car_serial_timer = QTimer()
        self.car_serial_timer.timeout.connect(self.read_car_serial_data)
        self.car_serial_timer.start(50)

    # ---------- 界面组件 ----------
    def create_serial_group(self):
        group = QGroupBox("电机串口")
        layout = QHBoxLayout()
        self.status_led = QLabel()
        self.status_led.setFixedSize(20, 20)
        self.status_led.setStyleSheet("background:gray;border-radius:10px")
        layout.addWidget(self.status_led)
        layout.addWidget(QLabel("端口:"))
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo)
        layout.addWidget(QLabel("波特率:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "115200"])
        self.baud_combo.setCurrentText("9600")
        layout.addWidget(self.baud_combo)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.scan_serial_ports)
        layout.addWidget(self.refresh_btn)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_serial_connection)
        layout.addWidget(self.connect_btn)
        # 断开按钮
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.clicked.connect(self.disconnect_serial)
        layout.addWidget(self.disconnect_btn)
        group.setLayout(layout)
        return group

    def create_car_group(self):
        group = QGroupBox("小车控制（独立串口）")
        layout = QVBoxLayout()
        # 串口配置行
        cfg_layout = QHBoxLayout()
        self.car_status_led = QLabel()
        self.car_status_led.setFixedSize(20, 20)
        self.car_status_led.setStyleSheet("background:gray;border-radius:10px")
        cfg_layout.addWidget(self.car_status_led)
        cfg_layout.addWidget(QLabel("端口:"))
        self.car_port_combo = QComboBox()
        cfg_layout.addWidget(self.car_port_combo)
        cfg_layout.addWidget(QLabel("波特率:"))
        self.car_baud_combo = QComboBox()
        self.car_baud_combo.addItems(["9600", "115200"])
        self.car_baud_combo.setCurrentText("9600")
        cfg_layout.addWidget(self.car_baud_combo)
        self.car_refresh_btn = QPushButton("刷新")
        self.car_refresh_btn.clicked.connect(self.scan_car_serial_ports)
        cfg_layout.addWidget(self.car_refresh_btn)
        self.car_connect_btn = QPushButton("连接")
        self.car_connect_btn.clicked.connect(self.toggle_car_serial_connection)
        cfg_layout.addWidget(self.car_connect_btn)
        # 断开按钮
        self.car_disconnect_btn = QPushButton("断开")
        self.car_disconnect_btn.clicked.connect(self.disconnect_car_serial)
        cfg_layout.addWidget(self.car_disconnect_btn)
        layout.addLayout(cfg_layout)

        # 控制按钮行
        btn_layout = QHBoxLayout()
        self.car_forward_btn = QPushButton("小车前进")
        self.car_backward_btn = QPushButton("小车后退")
        self.car_stop_btn = QPushButton("小车停止")
        self.car_forward_btn.clicked.connect(lambda: self.send_car_command('f'))
        self.car_backward_btn.clicked.connect(lambda: self.send_car_command('b'))
        self.car_stop_btn.clicked.connect(lambda: self.send_car_command('p'))
        btn_layout.addWidget(self.car_forward_btn)
        btn_layout.addWidget(self.car_backward_btn)
        btn_layout.addWidget(self.car_stop_btn)
        layout.addLayout(btn_layout)

        group.setLayout(layout)
        return group

    def create_motor_group(self):
        group = QGroupBox("单轴手动控制")
        layout = QVBoxLayout()
        # 轴选择
        axis_layout = QHBoxLayout()
        axis_layout.addWidget(QLabel("选择轴:"))
        self.motor_combo = QComboBox()
        self.motor_combo.addItems(["Y", "Z"])
        axis_layout.addWidget(self.motor_combo)
        layout.addLayout(axis_layout)
        # 方向按钮
        dir_layout = QHBoxLayout()
        self.forward_btn = QPushButton("正向移动")
        self.backward_btn = QPushButton("反向移动")
        dir_layout.addWidget(self.forward_btn)
        dir_layout.addWidget(self.backward_btn)
        layout.addLayout(dir_layout)
        # 速度设置
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("脉冲频率(Hz):"))
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(100, 10000)
        self.speed_spin.setValue(2000)
        self.speed_spin.valueChanged.connect(self.set_motor_speed)
        speed_layout.addWidget(self.speed_spin)
        layout.addLayout(speed_layout)
        # 脉冲数
        pulse_layout = QHBoxLayout()
        pulse_layout.addWidget(QLabel("脉冲数:"))
        self.pulse_spin = QSpinBox()
        self.pulse_spin.setRange(1, 50000)
        self.pulse_spin.setValue(1000)
        pulse_layout.addWidget(self.pulse_spin)
        layout.addLayout(pulse_layout)

        self.forward_btn.clicked.connect(lambda: self.send_manual_pulse(positive=True))
        self.backward_btn.clicked.connect(lambda: self.send_manual_pulse(positive=False))
        group.setLayout(layout)
        return group

    def create_auto_group(self):
        group = QGroupBox("自动扫描 (蛇形路径 + 连续飞拍)")
        layout = QVBoxLayout()
        # 路径选择
        path_layout = QHBoxLayout()
        self.path_label = QLabel("未选择保存路径")
        path_layout.addWidget(self.path_label)
        self.select_path_btn = QPushButton("选择路径")
        self.select_path_btn.clicked.connect(self.select_auto_path)
        path_layout.addWidget(self.select_path_btn)
        layout.addLayout(path_layout)

        grid = QGridLayout()
        grid.addWidget(QLabel("Y总脉冲数/行:"), 0, 0)
        self.y_pulse_spin = QSpinBox()
        self.y_pulse_spin.setRange(100, 100000)
        self.y_pulse_spin.setValue(5000)
        grid.addWidget(self.y_pulse_spin, 0, 1)

        grid.addWidget(QLabel("Z步进脉冲数:"), 1, 0)
        self.z_pulse_spin = QSpinBox()
        self.z_pulse_spin.setRange(1, 50000)
        self.z_pulse_spin.setValue(330)
        grid.addWidget(self.z_pulse_spin, 1, 1)

        grid.addWidget(QLabel("扫描行数:"), 2, 0)
        self.row_spin = QSpinBox()
        self.row_spin.setRange(1, 100)
        self.row_spin.setValue(5)
        grid.addWidget(self.row_spin, 2, 1)

        grid.addWidget(QLabel("拍照间隔(ms):"), 3, 0)
        self.capture_interval_spin = QSpinBox()
        self.capture_interval_spin.setRange(50, 2000)
        self.capture_interval_spin.setValue(200)
        grid.addWidget(self.capture_interval_spin, 3, 1)

        layout.addLayout(grid)

        self.start_btn = QPushButton("开始自动扫描")
        self.start_btn.clicked.connect(self.toggle_auto)
        layout.addWidget(self.start_btn)

        group.setLayout(layout)
        return group

    def create_preview_group(self):
        group = QGroupBox("相机预览")
        layout = QVBoxLayout()
        camera_layout = QHBoxLayout()
        camera_layout.addWidget(QLabel("相机:"))
        self.camera_combo = QComboBox()
        self.camera_combo.addItems(["USB相机"])
        if is_basler_camera_connected():
            self.camera_combo.addItem("Basler相机")
        camera_layout.addWidget(self.camera_combo)
        self.preview_btn = QPushButton("开始预览")
        self.preview_btn.clicked.connect(self.toggle_preview)
        camera_layout.addWidget(self.preview_btn)
        layout.addLayout(camera_layout)
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(500, 400)
        self.preview_label.setStyleSheet("border:1px solid gray; background:black;")
        self.preview_label.setText("未启动预览")
        layout.addWidget(self.preview_label)
        group.setLayout(layout)
        return group

    def create_captured_group(self):
        group = QGroupBox("最近拍摄")
        layout = QVBoxLayout()
        self.captured_label = QLabel()
        self.captured_label.setMinimumSize(500, 300)
        self.captured_label.setStyleSheet("border:1px solid gray; background:black;")
        layout.addWidget(self.captured_label)
        group.setLayout(layout)
        return group

    def create_status_group(self):
        group = QGroupBox("日志")
        layout = QVBoxLayout()
        self.status_text = QTextEdit()
        self.status_text.setMaximumHeight(150)
        layout.addWidget(self.status_text)
        group.setLayout(layout)
        return group

    # ---------- 电机串口功能 ----------
    def scan_serial_ports(self):
        self.port_combo.clear()
        for p in serial.tools.list_ports.comports():
            self.port_combo.addItem(p.device)

    def toggle_serial_connection(self):
        if not self.is_connected:
            try:
                self.serial_port = serial.Serial(self.port_combo.currentText(),
                                                 int(self.baud_combo.currentText()),
                                                 timeout=0.1)
                self.is_connected = True
                self.status_led.setStyleSheet("background:green;border-radius:10px")
                self.status_text.append("电机串口已连接")
            except Exception as e:
                self.status_text.append(f"电机串口连接失败: {e}")
        # 注意：如果已连接，点击连接按钮不做任何事（也可以改为重新连接，但通常不需要）

    def disconnect_serial(self):
        if self.is_connected:
            self.serial_port.close()
            self.is_connected = False
            self.status_led.setStyleSheet("background:gray;border-radius:10px")
            self.status_text.append("电机串口已断开")

    def send_serial_command(self, cmd):
        if self.is_connected:
            self.serial_port.write((cmd + "\n").encode())
            self.status_text.append(f"发送(电机): {cmd}")
        else:
            self.status_text.append("电机串口未连接，命令未发送")

    def read_serial_data(self):
        if self.is_connected and self.serial_port:
            try:
                while self.serial_port.in_waiting:
                    line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        self.status_text.append(f"←(电机) {line}")
                        if line == "OK":
                            self.on_motion_complete()
            except:
                pass

    def set_motor_speed(self, speed):
        if self.is_connected:
            self.send_serial_command(f"SPEED {speed}")

    # ---------- 小车串口功能 ----------
    def scan_car_serial_ports(self):
        self.car_port_combo.clear()
        for p in serial.tools.list_ports.comports():
            self.car_port_combo.addItem(p.device)

    def toggle_car_serial_connection(self):
        if not self.car_is_connected:
            try:
                self.car_serial_port = serial.Serial(self.car_port_combo.currentText(),
                                                     int(self.car_baud_combo.currentText()),
                                                     timeout=0.1)
                self.car_is_connected = True
                self.car_status_led.setStyleSheet("background:green;border-radius:10px")
                self.status_text.append("小车串口已连接")
            except Exception as e:
                self.status_text.append(f"小车串口连接失败: {e}")

    def disconnect_car_serial(self):
        if self.car_is_connected:
            self.car_serial_port.close()
            self.car_is_connected = False
            self.car_status_led.setStyleSheet("background:gray;border-radius:10px")
            self.status_text.append("小车串口已断开")

    def send_car_command(self, cmd):
        if self.car_is_connected:
            self.car_serial_port.write(cmd.encode())
            self.status_text.append(f"发送(小车): {cmd}")
        else:
            self.status_text.append("小车串口未连接")

    def read_car_serial_data(self):
        if self.car_is_connected and self.car_serial_port:
            try:
                while self.car_serial_port.in_waiting:
                    line = self.car_serial_port.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        self.status_text.append(f"←(小车) {line}")
            except:
                pass

    # ---------- 手动控制 ----------
    def send_manual_pulse(self, positive=True):
        axis = self.motor_combo.currentText()
        pulse = self.pulse_spin.value()
        if not positive:
            pulse = -pulse
        cmd = f"{axis}{pulse}"
        self.send_serial_command(cmd)

    # ---------- 相机 ----------
    def start_camera_preview(self):
        if self.camera_thread:
            self.camera_thread.stop()
        text = self.camera_combo.currentText()
        if "Basler" in text and BASLER_SUPPORT:
            self.camera_thread = BaslerCameraThread()
            self.status_text.append("启动Basler相机")
        else:
            self.camera_thread = CameraThread()
            self.camera_thread.set_camera_index(0)
        self.camera_thread.frame_signal.connect(self.update_preview)
        self.camera_thread.error_signal.connect(self.status_text.append)
        self.camera_thread.start()

    def toggle_preview(self):
        if self.camera_thread and self.camera_thread.is_running:
            self.camera_thread.stop()
            self.preview_btn.setText("开始预览")
            self.preview_label.setText("已停止")
        else:
            self.start_camera_preview()
            self.preview_btn.setText("停止预览")

    def update_preview(self, frame):
        self.current_frame = frame
        frame = cv2.resize(frame, (640, 480))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self.preview_label.setPixmap(QPixmap.fromImage(qimg))

    # ---------- 自动扫描 ----------
    def select_auto_path(self):
        self.current_path = QFileDialog.getExistingDirectory()
        if self.current_path:
            self.path_label.setText(self.current_path)
            self.img_dir = os.path.join(self.current_path, "images")
            os.makedirs(self.img_dir, exist_ok=True)

    def toggle_auto(self):
        if not self.auto_mode:
            if not self.current_path:
                self.status_text.append("请先选择保存路径")
                return
            if not self.is_connected:
                self.status_text.append("请先连接电机串口")
                return

            self.auto_mode = True
            self.start_btn.setText("停止扫描")

            self.y_total_pulses = self.y_pulse_spin.value()
            self.z_step_pulses = self.z_pulse_spin.value()
            self.total_rows = self.row_spin.value()
            self.capture_interval = self.capture_interval_spin.value()
            motor_speed = self.speed_spin.value()   # 使用手动控制模块的速度

            self.send_serial_command(f"SPEED {motor_speed}")
            self.send_serial_command(f"ACCEL 3000")

            self.current_row = 0
            self.y_direction = 1
            self.image_count = 1
            self.auto_state = "START"
            self.start_next_action()
        else:
            self.auto_mode = False
            self.capture_timer.stop()
            self.send_serial_command("STOP")
            self.start_btn.setText("开始自动扫描")
            self.status_text.append("扫描已停止")

    def start_next_action(self):
        if not self.auto_mode:
            return
        if self.auto_state == "START":
            self.start_y_move()
        # 其他状态等待运动完成回调

    def start_y_move(self):
        pulses = self.y_total_pulses * self.y_direction
        self.send_serial_command(f"Y{pulses}")
        self.auto_state = "MOVING_Y"
        self.capture_timer.start(self.capture_interval)
        self.status_text.append(f"开始Y移动，方向={'正向' if self.y_direction==1 else '反向'}，脉冲数={abs(pulses)}")

    def start_z_move(self):
        self.send_serial_command(f"Z{self.z_step_pulses}")
        self.auto_state = "MOVING_Z"
        # Z运动时不启动拍照
        self.status_text.append(f"Z轴步进 {self.z_step_pulses} 脉冲")

    def on_motion_complete(self):
        if not self.auto_mode:
            return
        if self.auto_state == "MOVING_Y":
            self.capture_timer.stop()
            self.status_text.append("Y移动完成，停止拍照")
            self.current_row += 1
            if self.current_row >= self.total_rows:
                self.status_text.append("扫描完成")
                self.auto_mode = False
                self.start_btn.setText("开始自动扫描")
                self.auto_state = "IDLE"
                return
            self.start_z_move()
        elif self.auto_state == "MOVING_Z":
            self.status_text.append("Z移动完成")
            self.y_direction = -self.y_direction
            self.start_y_move()

    def capture_once(self):
        if self.current_frame is not None and self.auto_mode:
            fname = os.path.join(self.img_dir, f"scan_{self.image_count:06d}.png")
            cv2.imwrite(fname, self.current_frame)
            self.status_text.append(f"拍照 {self.image_count}")
            rgb = cv2.cvtColor(self.current_frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch*w, QImage.Format_RGB888)
            self.captured_label.setPixmap(QPixmap.fromImage(qimg).scaled(500, 300, Qt.KeepAspectRatio))
            self.image_count += 1

    def closeEvent(self, e):
        if self.camera_thread:
            self.camera_thread.stop()
        if self.serial_port:
            self.serial_port.close()
        if self.car_serial_port:
            self.car_serial_port.close()
        e.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MotorControlGUI()
    w.show()
    sys.exit(app.exec_())