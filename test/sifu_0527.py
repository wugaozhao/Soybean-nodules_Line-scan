#可正常运转，8000频率下行进8000脉冲数仅需1.4s，约40mm/s

import sys
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QComboBox, QGroupBox, QTextEdit, QSpinBox,
                             QRadioButton, QButtonGroup, QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
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
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Arduino电机控制器")
        self.setFixedSize(550, 500)

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
        serial_layout.addWidget(self.port_combo)

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
        param_group = QGroupBox("电机参数设置")
        param_layout = QVBoxLayout()

        # 频率设置
        freq_layout = QHBoxLayout()
        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(1, 20000)
        self.freq_spin.setValue(1000)
        self.freq_spin.setSuffix(" Hz")
        freq_layout.addWidget(QLabel("脉冲频率:"))
        freq_layout.addWidget(self.freq_spin)

        self.set_freq_btn = QPushButton("设置频率")
        self.set_freq_btn.clicked.connect(self.set_frequency)
        freq_layout.addWidget(self.set_freq_btn)
        param_layout.addLayout(freq_layout)

        # 脉冲数设置
        pulse_layout = QHBoxLayout()
        self.pulse_spin = QSpinBox()
        self.pulse_spin.setRange(1, 999999)
        self.pulse_spin.setValue(1000)
        pulse_layout.addWidget(QLabel("脉冲数量:"))
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
        dir_layout.addWidget(QLabel("运行方向:"))
        dir_layout.addWidget(self.forward_radio)
        dir_layout.addWidget(self.reverse_radio)

        self.set_dir_btn = QPushButton("设置方向")
        self.set_dir_btn.clicked.connect(self.set_direction)
        dir_layout.addWidget(self.set_dir_btn)
        param_layout.addLayout(dir_layout)

        param_group.setLayout(param_layout)
        main_layout.addWidget(param_group)

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

        self.status_btn = QPushButton("查询状态")
        self.status_btn.clicked.connect(self.query_status)
        control_layout.addWidget(self.status_btn)

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

                # 启动串口接收线程
                self.serial_thread = SerialThread(self.serial_port)
                self.serial_thread.receive_signal.connect(self.update_log)
                self.serial_thread.start()
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"无法连接串口: {str(e)}")

    def disconnect_serial(self):
        """断开串口"""
        if self.serial_thread is not None:
            self.serial_thread.stop()
            self.serial_thread = None

        if self.serial_port is not None and self.serial_port.is_open:
            self.serial_port.close()
            self.log_text.append("串口已断开")

        self.connect_btn.setText("连接")
        self.set_controls_enabled(False)

    def set_controls_enabled(self, enabled):
        """启用/禁用控制按钮"""
        self.set_freq_btn.setEnabled(enabled)
        self.set_dir_btn.setEnabled(enabled)
        self.start_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(enabled)
        self.status_btn.setEnabled(enabled)
        self.freq_spin.setEnabled(enabled)
        self.pulse_spin.setEnabled(enabled)
        self.forward_radio.setEnabled(enabled)
        self.reverse_radio.setEnabled(enabled)

    def send_command(self, cmd):
        """发送指令到Arduino"""
        if self.serial_port is not None and self.serial_port.is_open:
            try:
                self.serial_port.write((cmd + '\n').encode('utf-8'))
                self.log_text.append(f"发送指令: {cmd}")
            except Exception as e:
                self.log_text.append(f"发送失败: {str(e)}")

    def set_frequency(self):
        """设置脉冲频率"""
        freq = self.freq_spin.value()
        self.send_command(f"F{freq}")

    def set_direction(self):
        """设置运行方向"""
        dir_code = self.dir_group.checkedId()
        self.send_command(f"D{dir_code}")

    def start_motor(self):
        """启动电机运行"""
        pulses = self.pulse_spin.value()
        self.send_command(f"P{pulses}")

    def stop_motor(self):
        """紧急停止电机"""
        self.send_command("S")

    def query_status(self):
        """查询电机运行状态"""
        self.send_command("R")

    def update_log(self, data):
        """更新日志显示"""
        self.log_text.append(f"接收: {data}")
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