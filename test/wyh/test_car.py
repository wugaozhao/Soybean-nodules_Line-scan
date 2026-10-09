import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QComboBox, QPushButton,
    QSpinBox, QVBoxLayout, QHBoxLayout, QTextEdit, QGroupBox, QMessageBox
)
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo


class StepperController(QWidget):
    def __init__(self):
        super().__init__()
        self.serial = QSerialPort(self)
        self.init_ui()
        self.refresh_ports()

    def init_ui(self):
        self.setWindowTitle('步进电机控制上位机')
        self.setMinimumWidth(400)

        # ----- 串口设置区域 -----
        port_group = QGroupBox('串口设置')
        port_layout = QHBoxLayout()

        self.port_combo = QComboBox()
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(['9600', '19200', '38400', '57600', '115200'])
        self.baud_combo.setCurrentText('9600')
        self.refresh_btn = QPushButton('刷新')
        self.open_btn = QPushButton('打开串口')

        port_layout.addWidget(QLabel('端口:'))
        port_layout.addWidget(self.port_combo)
        port_layout.addWidget(QLabel('波特率:'))
        port_layout.addWidget(self.baud_combo)
        port_layout.addWidget(self.refresh_btn)
        port_layout.addWidget(self.open_btn)
        port_group.setLayout(port_layout)

        # ----- 控制参数区域 -----
        ctrl_group = QGroupBox('运动参数')
        ctrl_layout = QHBoxLayout()

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 999999)
        self.steps_spin.setValue(2000)
        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(1, 10000)
        self.freq_spin.setValue(600)
        self.freq_spin.setSuffix(' Hz')
        self.dir_combo = QComboBox()
        self.dir_combo.addItems(['正转 (CW)', '反转 (CCW)'])
        self.send_btn = QPushButton('发送指令')
        self.send_btn.setEnabled(False)

        ctrl_layout.addWidget(QLabel('脉冲数:'))
        ctrl_layout.addWidget(self.steps_spin)
        ctrl_layout.addWidget(QLabel('频率:'))
        ctrl_layout.addWidget(self.freq_spin)
        ctrl_layout.addWidget(QLabel('方向:'))
        ctrl_layout.addWidget(self.dir_combo)
        ctrl_layout.addWidget(self.send_btn)
        ctrl_group.setLayout(ctrl_layout)

        # ----- 日志区域 -----
        log_group = QGroupBox('状态日志')
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)

        # ----- 主布局 -----
        main_layout = QVBoxLayout()
        main_layout.addWidget(port_group)
        main_layout.addWidget(ctrl_group)
        main_layout.addWidget(log_group)
        self.setLayout(main_layout)

        # ----- 信号连接 -----
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.open_btn.clicked.connect(self.toggle_serial)
        self.send_btn.clicked.connect(self.send_command)
        self.serial.readyRead.connect(self.read_data)

    def refresh_ports(self):
        self.port_combo.clear()
        ports = QSerialPortInfo.availablePorts()
        for port in ports:
            self.port_combo.addItem(port.portName())
        self.log('刷新串口列表')

    def toggle_serial(self):
        if self.serial.isOpen():
            self.serial.close()
            self.open_btn.setText('打开串口')
            self.send_btn.setEnabled(False)
            self.log('串口已关闭')
        else:
            port_name = self.port_combo.currentText()
            if not port_name:
                QMessageBox.warning(self, '错误', '请选择一个串口')
                return
            self.serial.setPortName(port_name)
            self.serial.setBaudRate(int(self.baud_combo.currentText()))
            if self.serial.open(QSerialPort.ReadWrite):
                self.open_btn.setText('关闭串口')
                self.send_btn.setEnabled(True)
                self.log(f'已打开串口 {port_name}')
            else:
                QMessageBox.critical(self, '错误', '无法打开串口')

    def send_command(self):
        if not self.serial.isOpen():
            return
        steps = self.steps_spin.value()
        freq = self.freq_spin.value()
        direction = 0 if self.dir_combo.currentIndex() == 0 else 1
        cmd = f'P,{steps},{freq},{direction}\n'
        self.serial.write(cmd.encode())
        self.log(f'发送: {cmd.strip()}')

    @pyqtSlot()
    def read_data(self):
        data = self.serial.readAll().data().decode(errors='ignore')
        if data:
            self.log(f'接收: {data.strip()}')

    def log(self, message):
        self.log_text.append(message)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = StepperController()
    window.show()
    sys.exit(app.exec_())