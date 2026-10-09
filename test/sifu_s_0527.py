#带加减速版，8000hz 7500脉冲数 37.5mm距离 1.13s —— 对应行频1571hz

import sys
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QComboBox,
                             QGroupBox, QTextEdit, QSpinBox, QRadioButton,
                             QButtonGroup, QMessageBox, QProgressBar)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QFont


# 串口接收线程
class SerialThread(QThread):
    receive_signal = pyqtSignal(str)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.is_running = True

    def run(self):
        while self.is_running and self.serial_port.is_open:
            try:
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.readline().decode('utf-8').strip()
                    if data:
                        self.receive_signal.emit(data)
            except Exception as e:
                self.receive_signal.emit(f"串口错误: {str(e)}")
                break

    def stop(self):
        self.is_running = False
        self.wait()


# 主窗口
class MotorControlWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.serial_thread = None
        self.status_timer = QTimer()  # 状态查询定时器
        self.init_ui()
        self.init_timer()

    def init_ui(self):
        self.setWindowTitle("Arduino电机控制器(加减速版)")
        self.setFixedSize(550, 580)

        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 串口连接区域
        serial_group = QGroupBox("串口连接")
        serial_layout = QHBoxLayout()

        self.port_combo = QComboBox()
        self.refresh_ports()
        serial_layout.addWidget(QLabel("端口:"))
        serial_layout.addWidget(self.port_combo, 1)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.baud_combo.setCurrentText("9600")
        serial_layout.addWidget(QLabel("波特率:"))
        serial_layout.addWidget(self.baud_combo)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_serial)
        serial_layout.addWidget(self.connect_btn)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        serial_layout.addWidget(self.refresh_btn)

        serial_group.setLayout(serial_layout)
        main_layout.addWidget(serial_group)

        # 电机参数设置区域
        param_group = QGroupBox("电机参数设置（修改后自动生效）")
        param_layout = QVBoxLayout()

        # 频率设置
        freq_layout = QHBoxLayout()
        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(1, 20000)
        self.freq_spin.setValue(1000)
        self.freq_spin.setSuffix(" Hz")
        self.freq_spin.valueChanged.connect(self.set_frequency)  # 值改变自动发送
        freq_layout.addWidget(QLabel("目标运行频率:"))
        freq_layout.addWidget(self.freq_spin)
        param_layout.addLayout(freq_layout)

        # 加减速时间设置
        accel_layout = QHBoxLayout()
        self.accel_spin = QSpinBox()
        self.accel_spin.setRange(0, 5000)
        self.accel_spin.setValue(500)
        self.accel_spin.setSuffix(" ms")
        self.accel_spin.valueChanged.connect(self.set_accel_time)  # 值改变自动发送
        accel_layout.addWidget(QLabel("加速时间:"))
        accel_layout.addWidget(self.accel_spin)

        self.decel_spin = QSpinBox()
        self.decel_spin.setRange(0, 5000)
        self.decel_spin.setValue(500)
        self.decel_spin.setSuffix(" ms")
        self.decel_spin.valueChanged.connect(self.set_decel_time)  # 值改变自动发送
        accel_layout.addWidget(QLabel("减速时间:"))
        accel_layout.addWidget(self.decel_spin)
        param_layout.addLayout(accel_layout)

        # 脉冲数设置
        pulse_layout = QHBoxLayout()
        self.pulse_spin = QSpinBox()
        self.pulse_spin.setRange(1, 999999)
        self.pulse_spin.setValue(2000)
        pulse_layout.addWidget(QLabel("单次运行脉冲数:"))
        pulse_layout.addWidget(self.pulse_spin)
        param_layout.addLayout(pulse_layout)

        # 方向设置
        dir_layout = QHBoxLayout()
        self.dir_group = QButtonGroup()
        self.forward_radio = QRadioButton("远离电机")
        self.reverse_radio = QRadioButton("靠近电机")
        self.forward_radio.setChecked(True)
        self.dir_group.addButton(self.forward_radio, 1)
        self.dir_group.addButton(self.reverse_radio, 0)
        self.dir_group.buttonClicked.connect(self.set_direction)  # 选择改变自动发送
        dir_layout.addWidget(QLabel("运行方向:"))
        dir_layout.addWidget(self.forward_radio)
        dir_layout.addWidget(self.reverse_radio)
        param_layout.addLayout(dir_layout)

        param_group.setLayout(param_layout)
        main_layout.addWidget(param_group)

        # 运行进度区域
        progress_group = QGroupBox("运行进度")
        progress_layout = QVBoxLayout()

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p% (%v/%m 脉冲)")
        progress_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("状态: 未连接")
        self.status_label.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(self.status_label)

        progress_group.setLayout(progress_layout)
        main_layout.addWidget(progress_group)

        # 控制按钮区域
        control_group = QGroupBox("运行控制")
        control_layout = QHBoxLayout()

        self.start_btn = QPushButton("启动运行")
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white; font-size: 14px; font-weight: bold;")
        self.start_btn.clicked.connect(self.start_motor)
        control_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("紧急停止")
        self.stop_btn.setStyleSheet("background-color: #f44336; color: white; font-size: 14px; font-weight: bold;")
        self.stop_btn.clicked.connect(self.stop_motor)
        control_layout.addWidget(self.stop_btn)

        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)

        # 日志显示区域
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        log_layout.addWidget(self.log_text)

        self.clear_btn = QPushButton("清空日志")
        self.clear_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(self.clear_btn)

        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

        # 初始禁用控制按钮
        self.set_controls_enabled(False)

    def init_timer(self):
        """初始化状态查询定时器"""
        self.status_timer.setInterval(500)  # 每500ms查询一次状态
        self.status_timer.timeout.connect(self.query_status)

    def refresh_ports(self):
        """刷新可用串口列表"""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(f"{port.device} - {port.description}")

    def toggle_serial(self):
        """连接/断开串口"""
        if self.serial_port is None or not self.serial_port.is_open:
            self.connect_serial()
        else:
            self.disconnect_serial()

    def connect_serial(self):
        """连接串口"""
        try:
            port_name = self.port_combo.currentText().split(" - ")[0]
            baud_rate = int(self.baud_combo.currentText())

            self.serial_port = serial.Serial(
                port=port_name,
                baudrate=baud_rate,
                timeout=1
            )

            if self.serial_port.is_open:
                self.log_text.append(f"成功连接到 {port_name}，波特率 {baud_rate}")
                self.connect_btn.setText("断开")
                self.set_controls_enabled(True)
                self.status_label.setText("状态: 已连接，电机停止")

                # 启动串口接收线程
                self.serial_thread = SerialThread(self.serial_port)
                self.serial_thread.receive_signal.connect(self.update_log)
                self.serial_thread.start()

                # 启动状态查询定时器
                self.status_timer.start()

                # 同步初始参数到Arduino
                QTimer.singleShot(500, self.sync_initial_params)
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"无法连接串口: {str(e)}")

    def disconnect_serial(self):
        """断开串口"""
        self.status_timer.stop()

        if self.serial_thread is not None:
            self.serial_thread.stop()
            self.serial_thread = None

        if self.serial_port is not None and self.serial_port.is_open:
            self.serial_port.close()
            self.log_text.append("串口已断开")

        self.connect_btn.setText("连接")
        self.set_controls_enabled(False)
        self.status_label.setText("状态: 未连接")
        self.progress_bar.setValue(0)

    def sync_initial_params(self):
        """同步上位机初始参数到Arduino"""
        self.set_frequency()
        self.set_accel_time()
        self.set_decel_time()
        self.set_direction()

    def set_controls_enabled(self, enabled):
        """启用/禁用控制按钮"""
        self.freq_spin.setEnabled(enabled)
        self.accel_spin.setEnabled(enabled)
        self.decel_spin.setEnabled(enabled)
        self.pulse_spin.setEnabled(enabled)
        self.forward_radio.setEnabled(enabled)
        self.reverse_radio.setEnabled(enabled)
        self.start_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(enabled)

    def send_command(self, cmd):
        """发送指令到Arduino"""
        if self.serial_port is not None and self.serial_port.is_open:
            try:
                self.serial_port.write((cmd + '\n').encode('utf-8'))
                self.log_text.append(f"发送指令: {cmd}")
            except Exception as e:
                self.log_text.append(f"发送失败: {str(e)}")

    def set_frequency(self):
        """设置目标频率（自动调用）"""
        if self.serial_port and self.serial_port.is_open:
            freq = self.freq_spin.value()
            self.send_command(f"F{freq}")

    def set_accel_time(self):
        """设置加速时间（自动调用）"""
        if self.serial_port and self.serial_port.is_open:
            time = self.accel_spin.value()
            self.send_command(f"A{time}")

    def set_decel_time(self):
        """设置减速时间（自动调用）"""
        if self.serial_port and self.serial_port.is_open:
            time = self.decel_spin.value()
            self.send_command(f"B{time}")

    def set_direction(self):
        """设置运行方向（自动调用）"""
        if self.serial_port and self.serial_port.is_open:
            dir_code = self.dir_group.checkedId()
            self.send_command(f"D{dir_code}")

    def start_motor(self):
        """启动电机运行"""
        pulses = self.pulse_spin.value()
        self.send_command(f"P{pulses}")
        self.progress_bar.setRange(0, pulses)

    def stop_motor(self):
        """紧急停止电机"""
        self.send_command("S")
        self.progress_bar.setValue(0)

    def query_status(self):
        """查询电机运行状态"""
        self.send_command("R")

    def update_log(self, data):
        """更新日志和状态显示"""
        self.log_text.append(f"接收: {data}")

        # 解析状态信息更新进度条和状态标签
        if data.startswith("状态:"):
            try:
                parts = data.split()
                status = parts[0].split(":")[1]
                progress_parts = parts[1].split(":")[1].split("/")
                current = int(progress_parts[0])
                total = int(progress_parts[1])

                self.progress_bar.setValue(current)
                self.progress_bar.setMaximum(total)

                if status == "运行中":
                    self.status_label.setText(f"状态: 运行中 | 当前频率: {parts[3]} Hz")
                    self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                else:
                    self.status_label.setText("状态: 已连接，电机停止")
                    self.status_label.setStyleSheet("color: black;")
            except:
                pass

        # 自动滚动到底部
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def closeEvent(self, event):
        """窗口关闭事件"""
        self.disconnect_serial()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MotorControlWindow()
    window.show()
    sys.exit(app.exec_())