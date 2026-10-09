"""
直线模组控制系统 - 上位机程序 (缓启动加速版)
引脚配置: DIR=9, PUL=10, ENA=11
"""

import sys
import serial
import serial.tools.list_ports
import threading
import time
from datetime import datetime
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *


class SerialThread(QThread):
    """串口通信线程类"""
    data_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.running = False

    def open_port(self, port, baudrate=115200, timeout=0.5):
        """打开串口"""
        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout
            )
            self.running = True
            return True
        except Exception as e:
            self.error_occurred.emit(f"打开串口失败: {str(e)}")
            return False

    def close_port(self):
        """关闭串口"""
        self.running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()

    def send_data(self, data):
        """发送数据"""
        if self.serial_port and self.serial_port.is_open:
            try:
                if not data.endswith('\n'):
                    data += '\n'
                self.serial_port.write(data.encode('utf-8'))
                return True
            except Exception as e:
                self.error_occurred.emit(f"发送数据失败: {str(e)}")
                return False
        return False

    def run(self):
        """线程主循环，持续接收数据"""
        while self.running:
            if self.serial_port and self.serial_port.is_open:
                try:
                    if self.serial_port.in_waiting > 0:
                        data = self.serial_port.readline()
                        if data:
                            decoded_data = data.decode('utf-8', errors='ignore').strip()
                            if decoded_data:
                                self.data_received.emit(decoded_data)
                except Exception as e:
                    self.error_occurred.emit(f"读取数据失败: {str(e)}")
                    time.sleep(0.01)
            time.sleep(0.01)


class MotorControlWindow(QMainWindow):
    """主窗口类（支持缓启动加速）"""

    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.init_ui()
        self.scan_serial_ports()

    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("直线模组控制系统")
        self.setGeometry(100, 100, 900, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 串口设置
        serial_group = QGroupBox("串口设置")
        serial_layout = QGridLayout()
        serial_layout.addWidget(QLabel("可用串口:"), 0, 0)
        self.serial_combo = QComboBox()
        serial_layout.addWidget(self.serial_combo, 0, 1)
        self.refresh_btn = QPushButton("刷新串口")
        self.refresh_btn.clicked.connect(self.scan_serial_ports)
        serial_layout.addWidget(self.refresh_btn, 0, 2)
        serial_layout.addWidget(QLabel("波特率:"), 1, 0)
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.baudrate_combo.setCurrentText("115200")
        serial_layout.addWidget(self.baudrate_combo, 1, 1)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_serial_connection)
        self.connect_btn.setStyleSheet("background-color: lightgreen")
        serial_layout.addWidget(self.connect_btn, 1, 2)
        serial_group.setLayout(serial_layout)
        main_layout.addWidget(serial_group)

        # 电机控制（新增启动频率 + 加速步数）
        motor_group = QGroupBox("直线模组控制")
        motor_layout = QGridLayout()

        motor_layout.addWidget(QLabel("运动方向:"), 0, 0)
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["前进-靠近电机", "后退-远离电机"])
        motor_layout.addWidget(self.direction_combo, 0, 1)

        motor_layout.addWidget(QLabel("总脉冲数:"), 1, 0)
        self.pulse_spinbox = QSpinBox()
        self.pulse_spinbox.setRange(1, 1000000)
        self.pulse_spinbox.setValue(2000)
        self.pulse_spinbox.setSuffix(" 脉冲")
        motor_layout.addWidget(self.pulse_spinbox, 1, 1)

        # ========== 新增：启动频率（缓慢加速起点）==========
        motor_layout.addWidget(QLabel("启动频率(慢):"), 2, 0)
        self.start_freq_spinbox = QSpinBox()
        self.start_freq_spinbox.setRange(100, 2000)
        self.start_freq_spinbox.setValue(300)
        self.start_freq_spinbox.setSuffix(" Hz")
        motor_layout.addWidget(self.start_freq_spinbox, 2, 1)

        # ========== 目标频率（全速）==========
        motor_layout.addWidget(QLabel("目标频率(快):"), 3, 0)
        self.freq_spinbox = QSpinBox()
        self.freq_spinbox.setRange(500, 50000)
        self.freq_spinbox.setValue(1500)
        self.freq_spinbox.setSuffix(" Hz")
        motor_layout.addWidget(self.freq_spinbox, 3, 1)

        # ========== 新增：加速步数==========
        motor_layout.addWidget(QLabel("加速步数:"), 4, 0)
        self.accel_steps_spinbox = QSpinBox()
        self.accel_steps_spinbox.setRange(50, 5000)
        self.accel_steps_spinbox.setValue(400)
        self.accel_steps_spinbox.setSuffix(" 步")
        motor_layout.addWidget(self.accel_steps_spinbox, 4, 1)

        self.move_btn = QPushButton("开始运动(缓启动)")
        self.move_btn.clicked.connect(self.send_movement_command)
        self.move_btn.setEnabled(False)
        self.move_btn.setStyleSheet("font-weight: bold; font-size: 14px; background-color:#4CAF50; color:white")
        motor_layout.addWidget(self.move_btn, 0, 2, 5, 1)

        self.emergency_stop_btn = QPushButton("紧急停止")
        self.emergency_stop_btn.clicked.connect(self.send_emergency_stop)
        self.emergency_stop_btn.setEnabled(False)
        self.emergency_stop_btn.setStyleSheet("background-color: red; color: white; font-weight: bold")
        motor_layout.addWidget(self.emergency_stop_btn, 0, 3, 5, 1)

        motor_group.setLayout(motor_layout)
        main_layout.addWidget(motor_group)

        # 调试功能
        debug_group = QGroupBox("调试功能")
        debug_layout = QHBoxLayout()
        self.test_direction_btn = QPushButton("测试方向")
        self.test_direction_btn.clicked.connect(self.test_direction)
        self.test_direction_btn.setEnabled(False)
        debug_layout.addWidget(self.test_direction_btn)
        self.reset_position_btn = QPushButton("重置位置")
        self.reset_position_btn.clicked.connect(self.reset_position)
        self.reset_position_btn.setEnabled(False)
        debug_layout.addWidget(self.reset_position_btn)
        self.query_status_btn = QPushButton("查询状态")
        self.query_status_btn.clicked.connect(self.query_status)
        self.query_status_btn.setEnabled(False)
        debug_layout.addWidget(self.query_status_btn)
        debug_group.setLayout(debug_layout)
        main_layout.addWidget(debug_group)

        # 状态
        status_group = QGroupBox("系统状态")
        status_layout = QGridLayout()
        status_layout.addWidget(QLabel("串口状态:"), 0, 0)
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("color: red; font-weight: bold")
        status_layout.addWidget(self.status_label, 0, 1)
        status_layout.addWidget(QLabel("电机状态:"), 1, 0)
        self.motor_status_label = QLabel("待机")
        self.motor_status_label.setStyleSheet("color: blue; font-weight: bold")
        status_layout.addWidget(self.motor_status_label, 1, 1)
        status_layout.addWidget(QLabel("当前位置:"), 2, 0)
        self.position_label = QLabel("0 脉冲")
        status_layout.addWidget(self.position_label, 2, 1)
        status_layout.addWidget(QLabel("引脚配置:"), 3, 0)
        self.pins_label = QLabel("DIR=9, PUL=10, ENA=11")
        self.pins_label.setStyleSheet("color: purple")
        status_layout.addWidget(self.pins_label, 3, 1)
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)

        # 加速提示
        accel_tip = QLabel("✅ 缓启动：电机从【启动频率】慢慢加速到【目标频率】，运行更平稳")
        accel_tip.setStyleSheet("color: green; font-weight: bold; padding:5px")
        main_layout.addWidget(accel_tip)

        # 日志
        log_group = QGroupBox("通信日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(250)
        log_layout.addWidget(self.log_text)
        self.clear_log_btn = QPushButton("清空日志")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_layout.addWidget(self.clear_log_btn)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

        self.statusBar().showMessage("就绪 - 支持缓启动加速")

    def scan_serial_ports(self):
        self.serial_combo.clear()
        ports = serial.tools.list_ports.comports()
        if not ports:
            self.serial_combo.addItem("无可用串口")
        else:
            for p in ports:
                self.serial_combo.addItem(p.device)

    def toggle_serial_connection(self):
        if self.serial_thread and self.serial_thread.running:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        port = self.serial_combo.currentText()
        baud = int(self.baudrate_combo.currentText())
        self.serial_thread = SerialThread()
        self.serial_thread.data_received.connect(self.handle_received_data)
        self.serial_thread.error_occurred.connect(self.handle_serial_error)

        if self.serial_thread.open_port(port, baud):
            self.serial_thread.start()
            self.connect_btn.setText("断开")
            self.connect_btn.setStyleSheet("background-color:lightcoral")
            self.status_label.setText("已连接")
            self.status_label.setStyleSheet("color:green; font-weight:bold")
            self.move_btn.setEnabled(True)
            self.emergency_stop_btn.setEnabled(True)
            self.test_direction_btn.setEnabled(True)
            self.reset_position_btn.setEnabled(True)
            self.query_status_btn.setEnabled(True)
            self.log_message(f"串口已连接：{port} {baud}bps", "success")

    def disconnect_serial(self):
        if self.serial_thread:
            self.serial_thread.close_port()
            self.serial_thread.wait(1000)  # 修复：增加超时
            self.serial_thread = None

        self.connect_btn.setText("连接")
        self.connect_btn.setStyleSheet("background-color: lightgreen")
        self.status_label.setText("未连接")
        self.status_label.setStyleSheet("color: red; font-weight: bold")
        self.motor_status_label.setText("待机")
        self.motor_status_label.setStyleSheet("color: blue; font-weight: bold")
        self.move_btn.setEnabled(False)
        self.emergency_stop_btn.setEnabled(False)
        self.test_direction_btn.setEnabled(False)
        self.reset_position_btn.setEnabled(False)
        self.query_status_btn.setEnabled(False)
        self.log_message("串口已断开", "info")

    # ===================== 核心：发送缓启动命令 =====================
    def send_movement_command(self):
        if not self.serial_thread or not self.serial_thread.running:
            self.log_message("错误：串口未连接", "error")
            return

        dir_code = "F" if "前进" in self.direction_combo.currentText() else "B"
        total_pulses = self.pulse_spinbox.value()
        start_freq = self.start_freq_spinbox.value()
        target_freq = self.freq_spinbox.value()
        accel_steps = self.accel_steps_spinbox.value()

        cmd = f"MOVE:{dir_code}:{total_pulses}:{start_freq}:{target_freq}:{accel_steps}"

        if self.serial_thread.send_data(cmd):
            self.motor_status_label.setText("运动中")
            self.motor_status_label.setStyleSheet("color: orange; font-weight: bold")
            self.log_message(f"发送命令：{cmd}", "command")

    def send_emergency_stop(self):
        if self.serial_thread:
            self.serial_thread.send_data("STOP")
            self.motor_status_label.setText("已急停")
            self.motor_status_label.setStyleSheet("color: red; font-weight: bold")
            self.log_message("已发送急停命令", "warning")

    def test_direction(self):
        if self.serial_thread:
            self.serial_thread.send_data("TEST:DIR")
            self.log_message("发送方向测试命令", "command")

    def reset_position(self):
        if self.serial_thread:
            self.serial_thread.send_data("RESET")
            self.log_message("发送位置重置命令", "command")

    def query_status(self):
        if self.serial_thread:
            self.serial_thread.send_data("STATUS?")
            self.log_message("发送状态查询命令", "command")

    # ===================== 修复：完整解析下位机状态 =====================
    def handle_received_data(self, data):
        self.log_message(f"接收：{data}", "receive")

        # 解析位置
        if data.startswith("POS:"):
            try:
                pos = data.split(":")[1]
                self.position_label.setText(f"{pos} 脉冲")
            except:
                pass

        # 解析状态（修复）
        if data.startswith("STATUS:"):
            try:
                status = data.split(":")[1]
                if status == "READY":
                    self.motor_status_label.setText("待机")
                    self.motor_status_label.setStyleSheet("color: blue; font-weight: bold")
                elif status == "MOVING":
                    self.motor_status_label.setText("运动中")
                    self.motor_status_label.setStyleSheet("color: orange; font-weight: bold")
                elif status == "COMPLETE":
                    self.motor_status_label.setText("运动完成")
                    self.motor_status_label.setStyleSheet("color: green; font-weight: bold")
                elif status == "STOPPED":
                    self.motor_status_label.setText("已停止")
                    self.motor_status_label.setStyleSheet("color: red; font-weight: bold")
            except:
                pass

    def handle_serial_error(self, e):
        self.log_message(f"错误：{e}", "error")

    def log_message(self, msg, t="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        color_map = {
            "error": "red",
            "warning": "orange",
            "success": "green",
            "command": "blue",
            "receive": "purple",
            "info": "black"
        }
        prefix_map = {
            "error": "[错误]",
            "warning": "[警告]",
            "success": "[成功]",
            "command": "[命令]",
            "receive": "[接收]",
            "info": "[信息]"
        }
        color = color_map.get(t, "black")
        prefix = prefix_map.get(t, "[信息]")
        self.log_text.append(f'<font color="{color}">[{ts}]{prefix} {msg}</font>')

    def clear_log(self):
        self.log_text.clear()
        self.log_message("日志已清空", "info")

    def closeEvent(self, e):
        self.disconnect_serial()
        e.accept()


def main():
    app = QApplication(sys.argv)
    w = MotorControlWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()