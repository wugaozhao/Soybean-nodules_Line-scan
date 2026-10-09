import sys
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import *
from PyQt5.QtCore import QTimer

class MotorController(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("伺服控制器 - 无使能自动使能版")
        self.setFixedSize(520, 460)
        self.ser = None
        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.read_serial)
        self.timer.start(50)

    def init_ui(self):
        main = QWidget()
        self.setCentralWidget(main)
        layout = QVBoxLayout(main)
        layout.setSpacing(14)

        # 串口
        g1 = QGroupBox("串口")
        h1 = QHBoxLayout()
        self.cb_port = QComboBox()
        self.btn_scan = QPushButton("刷新")
        self.btn_conn = QPushButton("连接")
        self.btn_disconn = QPushButton("断开")
        h1.addWidget(QLabel("串口:"))
        h1.addWidget(self.cb_port)
        h1.addWidget(self.btn_scan)
        h1.addWidget(self.btn_conn)
        h1.addWidget(self.btn_disconn)
        g1.setLayout(h1)

        # 参数
        g2 = QGroupBox("参数")
        f = QFormLayout()
        self.pulses = QLineEdit("10000")
        self.start = QLineEdit("2000")
        self.target = QLineEdit("20000")
        self.accel = QLineEdit("150")
        f.addRow("总脉冲:", self.pulses)
        f.addRow("启动频率:", self.start)
        f.addRow("目标频率:", self.target)
        f.addRow("加速步数:", self.accel)
        g2.setLayout(f)

        # 控制
        g3 = QGroupBox("控制")
        h3 = QHBoxLayout()
        self.btn_f = QPushButton("远离电机")
        self.btn_b = QPushButton("靠近电机")
        self.btn_stop = QPushButton("急停")
        self.btn_rst = QPushButton("复位")
        h3.addWidget(self.btn_f)
        h3.addWidget(self.btn_b)
        h3.addWidget(self.btn_stop)
        h3.addWidget(self.btn_rst)
        g3.setLayout(h3)

        # 状态
        g4 = QGroupBox("状态")
        f4 = QFormLayout()
        self.l_pos = QLabel("0")
        self.l_sta = QLabel("未连接")
        f4.addRow("当前位置:", self.l_pos)
        f4.addRow("状态:", self.l_sta)
        g4.setLayout(f4)

        layout.addWidget(g1)
        layout.addWidget(g2)
        layout.addWidget(g3)
        layout.addWidget(g4)

        self.btn_scan.clicked.connect(self.scan)
        self.btn_conn.clicked.connect(self.connect)
        self.btn_disconn.clicked.connect(self.disconn)
        self.btn_f.clicked.connect(lambda: self.go("F"))
        self.btn_b.clicked.connect(lambda: self.go("B"))
        self.btn_stop.clicked.connect(self.stop)
        self.btn_rst.clicked.connect(self.reset)
        self.scan()

    def scan(self):
        self.cb_port.clear()
        for p in serial.tools.list_ports.comports():
            self.cb_port.addItem(p.device)

    def connect(self):
        p = self.cb_port.currentText()
        if not p: return
        try:
            self.ser = serial.Serial(p, 115200, timeout=0.05)
            self.l_sta.setText("已连接")
            QMessageBox.information(self, "成功", "串口连接成功")
        except:
            QMessageBox.critical(self, "失败", "串口无法打开")

    def disconn(self):
        if self.ser: self.ser.close()
        self.ser = None
        self.l_sta.setText("未连接")

    def go(self, d):
        if not self.ser:
            QMessageBox.warning(self, "提示", "请先连接串口")
            return
        try:
            t = self.pulses.text()
            s = self.start.text()
            tar = self.target.text()
            a = self.accel.text()
            cmd = f"MOVE:{d}:{t}:{s}:{tar}:{a}\n"
            self.ser.write(cmd.encode())
        except:
            QMessageBox.critical(self, "错误", "指令发送失败")

    def stop(self):
        if self.ser: self.ser.write(b"STOP\n")
        self.l_sta.setText("停止")

    def reset(self):
        if self.ser: self.ser.write(b"RESET\n")
        self.l_pos.setText("0")

    def read_serial(self):
        if not self.ser or not self.ser.in_waiting: return
        try:
            data = self.ser.readline().decode("utf-8", "ignore").strip()
            if data.startswith("POS:"):
                self.l_pos.setText(data[4:])
            elif data.startswith("STATUS:"):
                self.l_sta.setText(data[7:])
        except:
            pass

    def closeEvent(self, e):
        if self.ser: self.ser.close()
        e.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MotorController()
    w.show()
    sys.exit(app.exec_())