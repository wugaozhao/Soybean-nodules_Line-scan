import sys
import serial
import time
from enum import Enum

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton,
    QTextEdit, QLabel, QWidget,
    QVBoxLayout, QHBoxLayout
)
from PyQt5.QtCore import QTimer, QObject, pyqtSignal

class State(Enum):
    IDLE = 0
    MOVING_FORWARD = 1
    SCANNING = 2
    SLIDING = 3
    MOVING_BACK = 4
    FINISHED = 5
    ERROR = 99

class SerialListener(QObject):
    received = pyqtSignal(str)

    def __init__(self, port='COM3', baudrate=9600):
        super().__init__()
        self.ser = serial.Serial(port, baudrate, timeout=0.1)
        time.sleep(2)

        self.timer = QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.start(50)   # 20 Hz

    def poll(self):
        if self.ser.in_waiting:
            line = self.ser.readline().decode().strip()
            if line:
                self.received.emit(line)

    def send(self, cmd: str):
        self.ser.write((cmd + '\n').encode())

    def close(self):
        if self.ser.is_open:
            self.ser.close()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("小车扫描系统上位机")

        self.state = State.IDLE
        self.serial = SerialListener('COM3')
        self.serial.received.connect(self.on_serial_msg)

        self.init_ui()

    def init_ui(self):
        self.label_state = QLabel("状态：IDLE")
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        self.btn_start = QPushButton("启动流程")
        self.btn_stop = QPushButton("急停")

        self.btn_start.clicked.connect(self.start_process)
        self.btn_stop.clicked.connect(self.emergency_stop)

        # 手动控制
        self.btn_f = QPushButton("前进 F")
        self.btn_z = QPushButton("扫描 Z")
        self.btn_p = QPushButton("平移 P")
        self.btn_b = QPushButton("回退 B")

        self.btn_f.clicked.connect(lambda: self.send_manual('F'))
        self.btn_z.clicked.connect(lambda: self.send_manual('Z'))
        self.btn_p.clicked.connect(lambda: self.send_manual('P'))
        self.btn_b.clicked.connect(lambda: self.send_manual('B'))

        layout = QVBoxLayout()
        layout.addWidget(self.label_state)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)

        hl = QHBoxLayout()
        for b in (self.btn_f, self.btn_z, self.btn_p, self.btn_b):
            hl.addWidget(b)
        layout.addLayout(hl)

        layout.addWidget(self.log)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def start_process(self):
        if self.state != State.IDLE:
            return
        self.log_msg("▶ 流程启动")
        self.enter_state(State.MOVING_FORWARD)

    def enter_state(self, new_state: State):
        self.state = new_state
        self.label_state.setText(f"状态：{new_state.name}")

        if new_state == State.MOVING_FORWARD:
            self.serial.send('F')
            self.log_msg("发送 F（前进）")

        elif new_state == State.SCANNING:
            self.serial.send('Z')
            self.log_msg("发送 Z（扫描）")

        elif new_state == State.SLIDING:
            self.serial.send('P')
            self.log_msg("发送 P（平移）")

        elif new_state == State.MOVING_BACK:
            self.serial.send('B')
            self.log_msg("发送 B（回退）")

        elif new_state == State.FINISHED:
            self.serial.send('E')
            self.log_msg("流程结束")
            self.enter_state(State.IDLE)

    def on_serial_msg(self, msg: str):
        self.log_msg(f"RX ← {msg}")

        # ---------- 正常应答 ----------
        if msg == 'OK':
            return

        if msg == 'ERR':
            self.enter_error("Arduino 返回 ERR")
            return

        # ---------- 到位事件 ----------
        if msg == 'Y_FWD_OK' and self.state == State.MOVING_FORWARD:
            self.log_msg("✓ 前进到位")
            self.enter_state(State.SCANNING)
            return

        if msg == 'Y_BWD_OK' and self.state == State.MOVING_BACK:
            self.log_msg("✓ 回退到位")
            self.enter_state(State.FINISHED)
            return

    def send_manual(self, cmd):
        self.serial.send(cmd)
        self.log_msg(f"[手动] TX → {cmd}")

    def emergency_stop(self):
        self.serial.send('S')
        self.log_msg("⛔ 急停")
        self.enter_state(State.IDLE)

    def enter_error(self, reason):
        self.state = State.ERROR
        self.label_state.setText("状态：ERROR")
        self.log_msg(f"❌ 错误：{reason}")
        self.serial.send('S')

    def log_msg(self, msg):
        self.log.append(msg)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
