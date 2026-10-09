# -*- coding: utf-8 -*-

import sys
from datetime import datetime

import serial
import serial.tools.list_ports
from PyQt5.QtCore import QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class SerialReaderThread(QThread):
    line_received = pyqtSignal(str)
    error_received = pyqtSignal(str)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.running = True

    def run(self):
        while self.running and self.serial_port and self.serial_port.is_open:
            try:
                raw = self.serial_port.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    self.line_received.emit(line)
            except Exception as exc:
                self.error_received.emit(f"串口接收异常: {exc}")
                break

    def stop(self):
        self.running = False
        self.wait(1500)


class MotorDebugWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.serial_thread = None

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(500)
        self.status_timer.timeout.connect(self.query_status)

        self.init_ui()
        self.refresh_ports()
        self.update_controls()

    def init_ui(self):
        self.setWindowTitle("简易电机调试")
        self.setFixedSize(520, 430)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        serial_group = QGroupBox("串口连接")
        serial_layout = QVBoxLayout()
        serial_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.baud_combo.setCurrentText("9600")
        serial_row.addWidget(QLabel("端口"))
        serial_row.addWidget(self.port_combo, 1)
        serial_row.addWidget(QLabel("波特率"))
        serial_row.addWidget(self.baud_combo)
        serial_layout.addLayout(serial_row)

        serial_btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_serial)
        serial_btn_row.addWidget(self.refresh_btn)
        serial_btn_row.addWidget(self.connect_btn)
        serial_layout.addLayout(serial_btn_row)
        serial_group.setLayout(serial_layout)
        main_layout.addWidget(serial_group)

        param_group = QGroupBox("电机参数")
        param_layout = QFormLayout()
        self.dir_combo = QComboBox()
        self.dir_combo.addItem("D0：远离电机端", 0)
        self.dir_combo.addItem("D1：靠近电机端", 1)
        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(1, 20000)
        self.freq_spin.setValue(500)
        self.freq_spin.setSuffix(" Hz")
        self.pulse_spin = QSpinBox()
        self.pulse_spin.setRange(1, 2000000000)
        self.pulse_spin.setValue(1000)
        param_layout.addRow("方向", self.dir_combo)
        param_layout.addRow("脉冲频率", self.freq_spin)
        param_layout.addRow("脉冲数量", self.pulse_spin)
        param_group.setLayout(param_layout)
        main_layout.addWidget(param_group)

        control_group = QGroupBox("控制")
        control_layout = QHBoxLayout()
        self.apply_btn = QPushButton("应用方向/频率")
        self.apply_btn.clicked.connect(self.apply_params)
        self.start_btn = QPushButton("开始运动")
        self.start_btn.clicked.connect(self.start_motion)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.stop_motion)
        control_layout.addWidget(self.apply_btn)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)

        status_group = QGroupBox("状态")
        status_layout = QVBoxLayout()
        self.status_label = QLabel("未连接")
        status_layout.addWidget(self.status_label)
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)

        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group, 1)

    def refresh_ports(self):
        current = self.port_combo.currentText().split(" - ")[0]
        self.port_combo.clear()
        for port in serial.tools.list_ports.comports():
            self.port_combo.addItem(f"{port.device} - {port.description}")
        if current:
            index = self.port_combo.findText(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    def toggle_serial(self):
        if self.serial_port and self.serial_port.is_open:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        if not self.port_combo.currentText():
            QMessageBox.warning(self, "串口", "未找到可用串口")
            return
        try:
            port_name = self.port_combo.currentText().split(" - ")[0]
            baud_rate = int(self.baud_combo.currentText())
            self.serial_port = serial.Serial(port_name, baud_rate, timeout=0.2)
            self.serial_thread = SerialReaderThread(self.serial_port)
            self.serial_thread.line_received.connect(self.handle_line)
            self.serial_thread.error_received.connect(self.log)
            self.serial_thread.start()
            self.connect_btn.setText("断开")
            self.status_timer.start()
            self.log(f"已连接: {port_name}, {baud_rate}")
            QTimer.singleShot(1800, self.apply_params)
            self.update_controls()
        except Exception as exc:
            QMessageBox.critical(self, "连接失败", str(exc))
            self.serial_port = None
            self.serial_thread = None
            self.update_controls()

    def disconnect_serial(self):
        self.status_timer.stop()
        if self.serial_port and self.serial_port.is_open:
            self.send_command("S")
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.serial_port = None
        self.connect_btn.setText("连接")
        self.status_label.setText("未连接")
        self.log("串口已断开")
        self.update_controls()

    def send_command(self, command, log_send=True):
        if not self.serial_port or not self.serial_port.is_open:
            if log_send:
                self.log("串口未连接")
            return False
        try:
            self.serial_port.write((command + "\n").encode("utf-8"))
            if log_send and command != "R":
                self.log(f">> {command}")
            return True
        except Exception as exc:
            self.log(f"发送失败: {exc}")
            return False

    def apply_params(self):
        if not self.is_serial_ready():
            return False
        ok1 = self.send_command(f"D{self.dir_combo.currentData()}")
        ok2 = self.send_command(f"F{self.freq_spin.value()}")
        self.query_status()
        return ok1 and ok2

    def start_motion(self):
        if not self.apply_params():
            return
        self.send_command(f"P{self.pulse_spin.value()}")
        self.status_label.setText("运动中")
        self.update_controls()

    def stop_motion(self):
        self.send_command("S")
        self.status_label.setText("已发送停止")
        self.update_controls()

    def query_status(self):
        self.send_command("R", log_send=False)

    def handle_line(self, line):
        if line.startswith("STATUS:"):
            self.status_label.setText(line)
            self.update_controls()
            return
        self.log(f"<< {line}")
        if line in ("EVENT:DONE", "EVENT:STOPPED"):
            self.query_status()
            self.update_controls()

    def is_serial_ready(self):
        return self.serial_port is not None and self.serial_port.is_open

    def update_controls(self):
        ready = self.is_serial_ready()
        self.apply_btn.setEnabled(ready)
        self.start_btn.setEnabled(ready)
        self.stop_btn.setEnabled(ready)
        self.dir_combo.setEnabled(ready)
        self.freq_spin.setEnabled(ready)
        self.pulse_spin.setEnabled(ready)
        self.port_combo.setEnabled(not ready)
        self.baud_combo.setEnabled(not ready)
        self.refresh_btn.setEnabled(not ready)

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        self.disconnect_serial()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MotorDebugWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
