"""
直线模组控制系统 - 上位机程序 (引脚修正版)
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
                # 确保数据以换行符结尾
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
                    # 读取串口数据
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
    """主窗口类"""

    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.init_ui()
        self.scan_serial_ports()

    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("直线模组控制系统 (引脚: DIR=9, PUL=10, ENA=11)")
        self.setGeometry(100, 100, 900, 750)

        # 设置主窗口中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout(central_widget)

        # 串口控制区域
        serial_group = QGroupBox("串口设置")
        serial_layout = QGridLayout()

        # 串口选择
        serial_layout.addWidget(QLabel("可用串口:"), 0, 0)
        self.serial_combo = QComboBox()
        self.serial_combo.setMinimumWidth(150)
        serial_layout.addWidget(self.serial_combo, 0, 1)

        # 刷新按钮
        self.refresh_btn = QPushButton("刷新串口")
        self.refresh_btn.clicked.connect(self.scan_serial_ports)
        serial_layout.addWidget(self.refresh_btn, 0, 2)

        # 波特率选择
        serial_layout.addWidget(QLabel("波特率:"), 1, 0)
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.baudrate_combo.setCurrentText("115200")
        serial_layout.addWidget(self.baudrate_combo, 1, 1)

        # 连接/断开按钮
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_serial_connection)
        self.connect_btn.setStyleSheet("background-color: lightgreen")
        serial_layout.addWidget(self.connect_btn, 1, 2)

        serial_group.setLayout(serial_layout)
        main_layout.addWidget(serial_group)

        # 电机控制区域
        motor_group = QGroupBox("直线模组控制")
        motor_layout = QGridLayout()

        # 方向选择
        motor_layout.addWidget(QLabel("运动方向:"), 0, 0)
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["前进 (靠近电机端)", "后退 (远离电机端)"])
        motor_layout.addWidget(self.direction_combo, 0, 1)

        # 脉冲数设置
        motor_layout.addWidget(QLabel("脉冲数:"), 1, 0)
        self.pulse_spinbox = QSpinBox()
        self.pulse_spinbox.setRange(1, 1000000)
        self.pulse_spinbox.setValue(1000)
        self.pulse_spinbox.setSuffix(" 脉冲")
        motor_layout.addWidget(self.pulse_spinbox, 1, 1)

        # 脉冲频率设置
        motor_layout.addWidget(QLabel("脉冲频率:"), 2, 0)
        self.frequency_spinbox = QSpinBox()
        self.frequency_spinbox.setRange(100, 10000)
        self.frequency_spinbox.setValue(1000)
        self.frequency_spinbox.setSuffix(" Hz")
        motor_layout.addWidget(self.frequency_spinbox, 2, 1)

        # 运动控制按钮
        self.move_btn = QPushButton("开始运动")
        self.move_btn.clicked.connect(self.send_movement_command)
        self.move_btn.setEnabled(False)
        self.move_btn.setStyleSheet("font-weight: bold; font-size: 14px")
        motor_layout.addWidget(self.move_btn, 0, 2, 3, 1)

        # 急停按钮
        self.emergency_stop_btn = QPushButton("紧急停止")
        self.emergency_stop_btn.clicked.connect(self.send_emergency_stop)
        self.emergency_stop_btn.setEnabled(False)
        self.emergency_stop_btn.setStyleSheet("background-color: red; color: white; font-weight: bold")
        motor_layout.addWidget(self.emergency_stop_btn, 0, 3, 3, 1)

        motor_group.setLayout(motor_layout)
        main_layout.addWidget(motor_group)

        # 调试功能区
        debug_group = QGroupBox("调试功能")
        debug_layout = QHBoxLayout()

        # 方向测试按钮
        self.test_direction_btn = QPushButton("测试方向")
        self.test_direction_btn.clicked.connect(self.test_direction)
        self.test_direction_btn.setEnabled(False)
        self.test_direction_btn.setToolTip("测试电机方向，观察实际运动方向")
        debug_layout.addWidget(self.test_direction_btn)

        # 重置位置按钮
        self.reset_position_btn = QPushButton("重置位置")
        self.reset_position_btn.clicked.connect(self.reset_position)
        self.reset_position_btn.setEnabled(False)
        debug_layout.addWidget(self.reset_position_btn)

        # 查询状态按钮
        self.query_status_btn = QPushButton("查询状态")
        self.query_status_btn.clicked.connect(self.query_status)
        self.query_status_btn.setEnabled(False)
        debug_layout.addWidget(self.query_status_btn)

        debug_group.setLayout(debug_layout)
        main_layout.addWidget(debug_group)

        # 状态信息区域
        status_group = QGroupBox("系统状态")
        status_layout = QGridLayout()

        # 连接状态
        status_layout.addWidget(QLabel("串口状态:"), 0, 0)
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("color: red; font-weight: bold")
        status_layout.addWidget(self.status_label, 0, 1)

        # 电机状态
        status_layout.addWidget(QLabel("电机状态:"), 1, 0)
        self.motor_status_label = QLabel("待机")
        self.motor_status_label.setStyleSheet("color: blue; font-weight: bold")
        status_layout.addWidget(self.motor_status_label, 1, 1)

        # 当前位置
        status_layout.addWidget(QLabel("当前位置:"), 2, 0)
        self.position_label = QLabel("0 脉冲")
        status_layout.addWidget(self.position_label, 2, 1)

        # 引脚状态
        status_layout.addWidget(QLabel("引脚配置:"), 3, 0)
        self.pins_label = QLabel("DIR=9, PUL=10, ENA=11")
        self.pins_label.setStyleSheet("color: purple")
        status_layout.addWidget(self.pins_label, 3, 1)

        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)

        # 方向调试提示
        direction_tip = QLabel("注意: 如果方向相反，请修改Arduino代码中的DIR_FORWARD和DIR_BACKWARD定义")
        direction_tip.setStyleSheet("color: orange; font-weight: bold; padding: 5px")
        main_layout.addWidget(direction_tip)

        # 日志区域
        log_group = QGroupBox("通信日志")
        log_layout = QVBoxLayout()

        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(250)
        log_layout.addWidget(self.log_text)

        # 日志控制按钮
        log_btn_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("清空日志")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_btn_layout.addWidget(self.clear_log_btn)

        log_btn_layout.addStretch()
        log_layout.addLayout(log_btn_layout)

        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

        # 底部状态栏
        self.statusBar().showMessage("就绪 - 引脚: DIR=9, PUL=10, ENA=11")

        # 设置样式
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid gray;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                padding: 5px 15px;
                font-size: 12px;
            }
        """)

    def scan_serial_ports(self):
        """扫描可用串口"""
        self.serial_combo.clear()
        ports = serial.tools.list_ports.comports()

        if not ports:
            self.log_message("警告: 未发现可用串口", "warning")
            self.serial_combo.addItem("无可用串口")
        else:
            for port in ports:
                self.serial_combo.addItem(port.device)
            self.log_message(f"发现 {len(ports)} 个串口", "info")

    def toggle_serial_connection(self):
        """切换串口连接状态"""
        if self.serial_thread and self.serial_thread.running:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        """连接串口"""
        port = self.serial_combo.currentText()
        baudrate = int(self.baudrate_combo.currentText())

        if not port or "无可用串口" in port:
            self.log_message("错误: 请选择有效串口", "error")
            return

        # 创建串口线程
        self.serial_thread = SerialThread()
        self.serial_thread.data_received.connect(self.handle_received_data)
        self.serial_thread.error_occurred.connect(self.handle_serial_error)

        if self.serial_thread.open_port(port, baudrate):
            self.serial_thread.start()
            self.connect_btn.setText("断开")
            self.connect_btn.setStyleSheet("background-color: lightcoral")
            self.status_label.setText("已连接")
            self.status_label.setStyleSheet("color: green; font-weight: bold")
            self.move_btn.setEnabled(True)
            self.emergency_stop_btn.setEnabled(True)
            self.test_direction_btn.setEnabled(True)
            self.reset_position_btn.setEnabled(True)
            self.query_status_btn.setEnabled(True)
            self.log_message(f"串口连接成功: {port} @ {baudrate} bps", "success")
            self.log_message("引脚配置: DIR=9, PUL=10, ENA=11", "info")
            self.statusBar().showMessage(f"已连接到 {port} - 引脚: DIR=9, PUL=10, ENA=11")
        else:
            self.log_message(f"连接失败: {port}", "error")

    def disconnect_serial(self):
        """断开串口连接"""
        if self.serial_thread:
            self.serial_thread.close_port()
            self.serial_thread.wait(1000)  # 等待线程结束
            self.serial_thread = None

        self.connect_btn.setText("连接")
        self.connect_btn.setStyleSheet("background-color: lightgreen")
        self.status_label.setText("未连接")
        self.status_label.setStyleSheet("color: red; font-weight: bold")
        self.move_btn.setEnabled(False)
        self.emergency_stop_btn.setEnabled(False)
        self.test_direction_btn.setEnabled(False)
        self.reset_position_btn.setEnabled(False)
        self.query_status_btn.setEnabled(False)
        self.log_message("串口已断开", "info")
        self.statusBar().showMessage("已断开连接")

    def send_movement_command(self):
        """发送运动命令"""
        if not self.serial_thread or not self.serial_thread.running:
            self.log_message("错误: 串口未连接", "error")
            return

        # 获取参数
        direction = self.direction_combo.currentText()
        pulses = self.pulse_spinbox.value()
        frequency = self.frequency_spinbox.value()

        # 确定方向代码
        dir_code = "F" if "前进" in direction else "B"

        # 构建命令
        command = f"MOVE:{dir_code}:{pulses}:{frequency}"

        # 发送命令
        if self.serial_thread.send_data(command):
            self.motor_status_label.setText("运动中")
            self.motor_status_label.setStyleSheet("color: orange; font-weight: bold")
            self.log_message(f"发送命令: {command}", "command")
            self.log_message(f"开始运动: 方向={direction}, 脉冲数={pulses}, 频率={frequency}Hz", "info")
        else:
            self.log_message("发送命令失败", "error")

    def send_emergency_stop(self):
        """发送紧急停止命令"""
        if not self.serial_thread or not self.serial_thread.running:
            return

        command = "STOP"
        if self.serial_thread.send_data(command):
            self.motor_status_label.setText("急停中")
            self.motor_status_label.setStyleSheet("color: red; font-weight: bold")
            self.log_message("发送紧急停止命令", "warning")

    def test_direction(self):
        """测试方向功能"""
        if not self.serial_thread or not self.serial_thread.running:
            self.log_message("错误: 串口未连接", "error")
            return

        command = "TEST:DIRECTION"
        if self.serial_thread.send_data(command):
            self.log_message("发送方向测试命令", "command")
            self.log_message("正在测试方向，请观察电机运动...", "info")

    def reset_position(self):
        """重置位置计数器"""
        if not self.serial_thread or not self.serial_thread.running:
            self.log_message("错误: 串口未连接", "error")
            return

        command = "RESET"
        if self.serial_thread.send_data(command):
            self.log_message("发送重置位置命令", "command")

    def query_status(self):
        """查询状态"""
        if not self.serial_thread or not self.serial_thread.running:
            self.log_message("错误: 串口未连接", "error")
            return

        command = "STATUS?"
        if self.serial_thread.send_data(command):
            self.log_message("发送状态查询命令", "command")

    def handle_received_data(self, data):
        """处理接收到的数据"""
        # 解析数据
        if data.startswith("STATUS:"):
            # 状态信息
            parts = data.split(":")
            if len(parts) >= 2:
                status = parts[1]
                if status == "READY":
                    self.motor_status_label.setText("待机")
                    self.motor_status_label.setStyleSheet("color: blue; font-weight: bold")
                elif status == "MOVING":
                    self.motor_status_label.setText("运动中")
                    self.motor_status_label.setStyleSheet("color: orange; font-weight: bold")
                elif status == "STOPPED":
                    self.motor_status_label.setText("已停止")
                    self.motor_status_label.setStyleSheet("color: red; font-weight: bold")
                elif status == "COMPLETE":
                    self.motor_status_label.setText("运动完成")
                    self.motor_status_label.setStyleSheet("color: green; font-weight: bold")

        elif data.startswith("POS:"):
            # 位置信息
            parts = data.split(":")
            if len(parts) >= 2:
                try:
                    position = int(parts[1])
                    self.position_label.setText(f"{position} 脉冲")
                except ValueError:
                    pass

        # 显示接收到的数据
        self.log_message(f"接收: {data}", "receive")

    def handle_serial_error(self, error_msg):
        """处理串口错误"""
        self.log_message(f"串口错误: {error_msg}", "error")
        self.statusBar().showMessage(f"错误: {error_msg}")

    def log_message(self, message, msg_type="info"):
        """记录日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")

        # 根据消息类型设置颜色
        if msg_type == "error":
            color = "red"
            prefix = "[错误]"
        elif msg_type == "warning":
            color = "orange"
            prefix = "[警告]"
        elif msg_type == "success":
            color = "green"
            prefix = "[成功]"
        elif msg_type == "command":
            color = "blue"
            prefix = "[命令]"
        elif msg_type == "receive":
            color = "purple"
            prefix = "[接收]"
        else:
            color = "black"
            prefix = "[信息]"

        # 添加格式化的消息
        formatted_message = f'<font color="{color}">[{timestamp}]{prefix} {message}</font>'
        self.log_text.append(formatted_message)

        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_log(self):
        """清空日志"""
        self.log_text.clear()
        self.log_message("日志已清空", "info")

    def closeEvent(self, event):
        """窗口关闭事件"""
        self.disconnect_serial()
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)

    # 设置应用程序信息
    app.setApplicationName("直线模组控制系统")
    app.setOrganizationName("科研实验室")

    # 创建并显示窗口
    window = MotorControlWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()