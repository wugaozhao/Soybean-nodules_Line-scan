import sys
import os
import cv2
import numpy as np
import ctypes
from ctypes import *
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QGroupBox, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QIODevice
from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo

# ========== 相机SDK ==========
MV_SDK_PATH = r"D:\MVS\MVS\Development\Samples\Python\MvImport"
sys.path.append(MV_SDK_PATH)
from MvCameraControl_class import *

class ControlPanel(QMainWindow):
    data_received = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("单次往返 + 相机自动启停 + 自动拼接长图")
        self.resize(500, 480)  # ----- 增加高度以容纳新控件 -----

        # ---------- 串口 ----------
        self.serial = QSerialPort(self)
        self.serial.readyRead.connect(self.on_serial_data)
        self.data_received.connect(self.handle_received_line)
        self.is_connected = False
        self.serial_buffer = ""

        # ---------- 相机 ----------
        self.cam = None
        self.is_cam_opened = False
        self.is_forward_capturing = False
        self.frame_counter = 0
        self.save_dir = None

        # 拼接缓存
        self.captured_frames = []
        self.stitch_height = 100

        # 预览定时器
        self.preview_timer = QTimer()
        self.preview_timer.timeout.connect(self.fetch_and_process)
        self.preview_timer.start(30)

        # ---------- UI ----------
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # 串口设置区
        group_serial = QGroupBox("串口设置")
        layout_serial = QHBoxLayout()
        self.combo_port = QComboBox()
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        self.combo_baud = QComboBox()
        self.combo_baud.addItems(["9600", "19200", "38400", "115200"])
        self.combo_baud.setCurrentText("9600")
        self.btn_open = QPushButton("打开串口")
        self.btn_open.clicked.connect(self.toggle_serial)
        layout_serial.addWidget(QLabel("端口:"))
        layout_serial.addWidget(self.combo_port)
        layout_serial.addWidget(self.btn_refresh)
        layout_serial.addWidget(QLabel("波特率:"))
        layout_serial.addWidget(self.combo_baud)
        layout_serial.addWidget(self.btn_open)
        group_serial.setLayout(layout_serial)
        main_layout.addWidget(group_serial)

        # 脉冲设置区
        group_pulse = QGroupBox("脉冲设置")
        layout_pulse = QHBoxLayout()
        layout_pulse.addWidget(QLabel("单程脉冲数:"))
        self.edit_pulse = QLineEdit("100000")
        self.edit_pulse.setFixedWidth(100)
        layout_pulse.addWidget(self.edit_pulse)
        self.btn_set = QPushButton("设置")
        self.btn_set.clicked.connect(self.set_pulses)
        layout_pulse.addWidget(self.btn_set)
        layout_pulse.addStretch()
        group_pulse.setLayout(layout_pulse)
        main_layout.addWidget(group_pulse)

        # ----- 新增：频率设置区 -----
        group_freq = QGroupBox("频率设置")
        layout_freq = QHBoxLayout()
        layout_freq.addWidget(QLabel("脉冲频率(Hz):"))
        self.edit_freq = QLineEdit("1000")
        self.edit_freq.setFixedWidth(100)
        layout_freq.addWidget(self.edit_freq)
        self.btn_set_freq = QPushButton("设置频率")
        self.btn_set_freq.clicked.connect(self.set_frequency)
        layout_freq.addWidget(self.btn_set_freq)
        layout_freq.addStretch()
        group_freq.setLayout(layout_freq)
        main_layout.addWidget(group_freq)
        # ----- 新增结束 -----

        # 相机参数区
        group_camera = QGroupBox("相机参数（启动时自动应用）")
        layout_camera = QHBoxLayout()
        layout_camera.addWidget(QLabel("曝光(us):"))
        self.edit_exposure = QLineEdit("5000")
        self.edit_exposure.setFixedWidth(80)
        layout_camera.addWidget(self.edit_exposure)
        self.btn_set_exp = QPushButton("设置曝光")
        self.btn_set_exp.clicked.connect(lambda: self.set_exposure(apply=True))
        layout_camera.addWidget(self.btn_set_exp)
        layout_camera.addWidget(QLabel("行频(Hz):"))
        self.edit_line_rate = QLineEdit("372")
        self.edit_line_rate.setFixedWidth(80)
        layout_camera.addWidget(self.edit_line_rate)
        self.btn_set_line = QPushButton("设置行频")
        self.btn_set_line.clicked.connect(lambda: self.set_line_rate(apply=True))
        layout_camera.addWidget(self.btn_set_line)
        layout_camera.addStretch()
        group_camera.setLayout(layout_camera)
        main_layout.addWidget(group_camera)

        # 运动控制区
        group_ctrl = QGroupBox("运动控制")
        layout_ctrl = QHBoxLayout()
        self.btn_start = QPushButton("启动一次往返")
        self.btn_start.clicked.connect(self.start_once)
        self.btn_stop = QPushButton("紧急停止")
        self.btn_stop.clicked.connect(self.emergency_stop)
        layout_ctrl.addWidget(self.btn_start)
        layout_ctrl.addWidget(self.btn_stop)
        layout_ctrl.addStretch()
        group_ctrl.setLayout(layout_ctrl)
        main_layout.addWidget(group_ctrl)

        # 状态栏
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("font-weight: bold; color: red")
        main_layout.addWidget(self.status_label)

        self.create_today_folder()
        self.refresh_ports()

    # ------------------ 文件夹创建 ------------------
    def create_today_folder(self):
        try:
            today_str = datetime.now().strftime("%Y%m%d")
            dir_path = os.path.join("D:\\", today_str)
            os.makedirs(dir_path, exist_ok=True)
            self.status_label.setText(f"保存文件夹: {dir_path}")
            self.save_dir = dir_path
            return True
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法创建 D 盘文件夹: {str(e)}")
            self.save_dir = None
            return False

    # ------------------ 串口操作 ------------------
    def refresh_ports(self):
        self.combo_port.clear()
        for port in QSerialPortInfo.availablePorts():
            self.combo_port.addItem(port.portName())

    def toggle_serial(self):
        if self.is_connected:
            self.close_serial()
        else:
            self.open_serial()

    def open_serial(self):
        if self.combo_port.count() == 0:
            QMessageBox.warning(self, "警告", "没有可用串口")
            return
        port_name = self.combo_port.currentText()
        baud = int(self.combo_baud.currentText())
        self.serial.setPortName(port_name)
        self.serial.setBaudRate(baud)
        self.serial.setDataBits(QSerialPort.Data8)
        self.serial.setParity(QSerialPort.NoParity)
        self.serial.setStopBits(QSerialPort.OneStop)
        self.serial.setFlowControl(QSerialPort.NoFlowControl)
        if self.serial.open(QIODevice.ReadWrite):
            self.is_connected = True
            self.btn_open.setText("关闭串口")
            self.status_label.setText("串口已打开")
            self.status_label.setStyleSheet("color: green")
            self.serial_buffer = ""
        else:
            QMessageBox.critical(self, "错误", "无法打开串口")

    def close_serial(self):
        if self.serial.isOpen():
            self.serial.close()
        self.is_connected = False
        self.btn_open.setText("打开串口")
        self.status_label.setText("串口已关闭")
        self.status_label.setStyleSheet("color: red")

    def send_command(self, cmd):
        if not self.is_connected:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return False
        if self.serial.isOpen():
            self.serial.write((cmd + "\n").encode())
            self.status_label.setText(f"已发送: {cmd}")
            return True
        return False

    def on_serial_data(self):
        if not self.is_connected:
            return
        data = self.serial.readAll().data().decode(errors="ignore")
        self.serial_buffer += data
        while "\n" in self.serial_buffer:
            line, self.serial_buffer = self.serial_buffer.split("\n", 1)
            line = line.strip()
            if line:
                self.data_received.emit(line)

    def handle_received_line(self, line):
        if line == "STARTED":
            self.is_forward_capturing = True
            self.captured_frames.clear()
            self.status_label.setText("正向运动进行中（采集缓存）")

        elif line == "FORWARD_END":
            self.is_forward_capturing = False
            self.close_camera()
            self.status_label.setText("正向结束，开始拼接长图...")
            self.save_stitch_image()

        elif line == "ROUND_TRIP_END":
            self.status_label.setText("往返运动结束 ✅ 长图已保存")
            self.status_label.setStyleSheet("color: blue")

        elif line == "STOPPED":
            self.is_forward_capturing = False
            self.close_camera()
            self.status_label.setText("已停止")

        elif line.startswith("PULSES SET TO"):
            self.status_label.setText(f"脉冲已设为: {line[13:]}")

        # ----- 新增：处理频率设置响应 -----
        elif line.startswith("FREQ SET TO"):
            self.status_label.setText(f"频率已设为: {line[12:]} Hz")
        # ----- 新增结束 -----

        elif line == "STOP FIRST":
            QMessageBox.information(self, "提示", "请先停止运动再设置脉冲")

        else:
            self.status_label.setText(line)

    # ------------------ 拼接长图 ------------------
    def save_stitch_image(self):
        try:
            if not self.captured_frames:
                return
            h = self.stitch_height
            strip_list = []
            for frame in self.captured_frames:
                ih, iw = frame.shape[:2]
                y1 = ih // 2 - h // 2
                y2 = y1 + h
                strip = frame[y1:y2, :]
                strip_list.append(strip)
            final_image = np.vstack(strip_list)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = os.path.join(self.save_dir, f"长图_{timestamp}.jpg")
            cv2.imwrite(save_path, final_image)
            self.status_label.setText(f"长图已保存：{len(strip_list)}行拼接完成")
        except Exception as e:
            self.status_label.setText(f"拼接失败: {str(e)}")

    # ------------------ 相机操作 ------------------
    def open_camera(self):
        if self.is_cam_opened:
            return True
        try:
            deviceList = MV_CC_DEVICE_INFO_LIST()
            ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE, deviceList)
            if ret != 0 or deviceList.nDeviceNum == 0:
                QMessageBox.warning(self, "错误", "未发现相机")
                return False
            self.cam = MvCamera()
            stDeviceInfo = cast(deviceList.pDeviceInfo[0], POINTER(MV_CC_DEVICE_INFO)).contents
            ret = self.cam.MV_CC_CreateHandle(stDeviceInfo)
            if ret != 0:
                QMessageBox.critical(self, "错误", f"创建相机句柄失败: {ret}")
                return False
            ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
            if ret != 0:
                QMessageBox.critical(self, "错误", f"打开相机失败: {ret}")
                return False
            self.cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
            self.cam.MV_CC_SetEnumValue("PixelFormat", 0x02180014)
            self.cam.MV_CC_SetEnumValue("BalanceWhiteAuto", 2)
            self.set_exposure(apply=True)
            self.set_line_rate(apply=True)
            ret = self.cam.MV_CC_StartGrabbing()
            if ret != 0:
                QMessageBox.critical(self, "错误", f"开始采集失败: {ret}")
                return False
            self.is_cam_opened = True
            self.status_label.setText("相机已打开（正向采集）")
            return True
        except Exception as e:
            QMessageBox.critical(self, "异常", f"打开相机异常: {str(e)}")
            return False

    def close_camera(self):
        if not self.is_cam_opened:
            return
        if self.cam:
            try:
                self.cam.MV_CC_StopGrabbing()
                self.cam.MV_CC_CloseDevice()
                self.cam.MV_CC_DestroyHandle()
            except:
                pass
            self.cam = None
        self.is_cam_opened = False
        self.is_forward_capturing = False

    def set_exposure(self, apply=False):
        try:
            exp = float(self.edit_exposure.text())
            if self.cam and apply and self.is_cam_opened:
                self.cam.MV_CC_SetFloatValue("ExposureTime", exp)
            self.status_label.setText(f"曝光设定: {exp} us")
        except:
            QMessageBox.warning(self, "警告", "曝光值无效")

    def set_line_rate(self, apply=False):
        try:
            rate = float(self.edit_line_rate.text())
            if self.cam and apply and self.is_cam_opened:
                self.cam.MV_CC_SetFloatValue("AcquisitionLineRate", rate)
            self.status_label.setText(f"行频设定: {rate} Hz")
        except:
            QMessageBox.warning(self, "警告", "行频值无效")

    def fetch_and_process(self):
        if not self.is_cam_opened or not self.cam:
            return
        try:
            stFrameInfo = MV_FRAME_OUT()
            memset(byref(stFrameInfo), 0, sizeof(stFrameInfo))
            ret = self.cam.MV_CC_GetImageBuffer(stFrameInfo, 50)
            if ret != 0:
                return
            w = stFrameInfo.stFrameInfo.nWidth
            h = stFrameInfo.stFrameInfo.nHeight
            pData = stFrameInfo.pBufAddr
            arr = np.ctypeslib.as_array(cast(pData, POINTER(c_ubyte)), shape=(h * w * 3,))
            img = arr.reshape((h, w, 3))
            bgr_img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            if self.is_forward_capturing:
                self.captured_frames.append(bgr_img)
            self.cam.MV_CC_FreeImageBuffer(stFrameInfo)
        except Exception as e:
            self.status_label.setText(f"取图错误: {str(e)[:40]}")

    # ------------------ 运动控制 ------------------
    def start_once(self):
        if not self.is_connected:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        if self.is_forward_capturing:
            QMessageBox.warning(self, "警告", "电机正在运动中")
            return
        if not self.open_camera():
            return
        self.frame_counter = 0
        self.send_command("START")

    def emergency_stop(self):
        self.send_command("STOP")
        self.is_forward_capturing = False
        self.close_camera()

    def set_pulses(self):
        if self.is_forward_capturing:
            QMessageBox.warning(self, "警告", "请先停止运动再设置脉冲数")
            return
        text = self.edit_pulse.text().strip()
        if not text.isdigit():
            QMessageBox.warning(self, "警告", "脉冲数必须为正整数")
            return
        val = int(text)
        if val <= 0 or val > 1000000:
            QMessageBox.warning(self, "警告", "脉冲数范围: 1 ~ 1000000")
            return
        self.send_command(f"PULSES {val}")

    # ----- 新增：设置脉冲频率 -----
    def set_frequency(self):
        if self.is_forward_capturing:
            QMessageBox.warning(self, "警告", "请先停止运动再设置频率")
            return
        text = self.edit_freq.text().strip()
        if not text.isdigit():
            QMessageBox.warning(self, "警告", "频率必须为正整数")
            return
        val = int(text)
        if val <= 0 or val > 500000:  # 可根据实际驱动器范围调整
            QMessageBox.warning(self, "警告", "频率范围: 1 ~ 500000 Hz")
            return
        self.send_command(f"FREQ {val}")
    # ----- 新增结束 -----

    def closeEvent(self, event):
        self.close_serial()
        self.close_camera()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ControlPanel()
    window.show()
    sys.exit(app.exec_())