# =========================
# main.py
# =========================
import sys
from PyQt5.QtWidgets import QApplication
from ui import MainWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

# =========================
# camera.py
# =========================
import sys
import threading
from ctypes import *

# 海康SDK路径（改成你自己的路径）
sys.path.append(r"D:\MVS\MVS\Development\Samples\Python\MvImport")
from MvCameraControl_class import *

class CameraThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.cam = MvCamera()
        self.running = False
        self.frames = []
        self.current_img = None  # 实时图像
        self.daemon = True

    def open(self):
        deviceList = MV_CC_DEVICE_INFO_LIST()
        ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, deviceList)
        if ret != 0 or deviceList.nDeviceNum == 0:
            raise Exception("未找到相机，请检查连接")

        stDeviceList = cast(deviceList.pDeviceInfo[0], POINTER(MV_CC_DEVICE_INFO)).contents
        self.cam.MV_CC_CreateHandle(stDeviceList)
        self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        self.cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
        self.cam.MV_CC_StartGrabbing()

    def start_grab(self):
        self.frames.clear()
        self.running = True

    def stop_grab(self):
        self.running = False

    def run(self):
        stFrameInfo = MV_FRAME_OUT_INFO_EX()
        buf_size = 1920 * 1200 * 4
        p_buf = (c_ubyte * buf_size)()

        while True:
            if self.running:
                ret = self.cam.MV_CC_GetOneFrame(p_buf, buf_size, stFrameInfo, 100)
                if ret == 0:
                    w = stFrameInfo.nWidth
                    h = stFrameInfo.nHeight
                    data = np.ctypeslib.as_array(p_buf, shape=(stFrameInfo.nFrameLen,))

                    if stFrameInfo.enPixelType == 17301505:  # RGB8
                        img = data.reshape((h, w, 3))
                    else:
                        img = data.reshape((h, w))

                    self.current_img = img.copy()
                    self.frames.append(img)

    def get_current_image(self):
        return self.current_img

    def stitch(self):
        if not self.frames:
            return None
        return np.vstack(self.frames)

# =========================
# serial_ctrl.py
# =========================
import serial

class SerialController:
    def __init__(self, port="COM3", baud=115200):
        self.ser = None
        try:
            self.ser = serial.Serial(port, baud, timeout=0.1)
        except:
            print("串口未连接")

    def send(self, cmd):
        if self.ser and self.ser.is_open:
            self.ser.write((cmd + "\n").encode())

    def read(self):
        if self.ser and self.ser.in_waiting:
            try:
                return self.ser.readline().decode().strip()
            except:
                return None
        return None

# =========================
# state_machine.py
# =========================
from enum import Enum

class State(Enum):
    WAIT_QR = 0
    STOP_CAR = 1
    FORWARD_SCAN = 2
    SAVE_FORWARD = 3
    BACKWARD_SCAN = 4
    SAVE_BACKWARD = 5

# =========================
# controller.py
# =========================
from state_machine import State
import os

class Controller:
    def __init__(self, cam, serial):
        self.cam = cam
        self.serial = serial
        self.state = State.WAIT_QR
        self.target_distance = 100
        self.current_pos = 0
        self.start_pos = 0
        self.save_path = ""

    def set_save_path(self, path):
        self.save_path = path

    def update(self, qr_detected):
        recv = self.serial.read()
        if recv and recv.startswith("POS"):
            try:
                self.current_pos = float(recv.split(":")[1])
            except:
                pass

        if self.state == State.WAIT_QR:
            if qr_detected:
                self.serial.send("S")
                self.state = State.STOP_CAR

        elif self.state == State.STOP_CAR:
            if recv == "OK_S":
                self.serial.send("F")
                self.cam.start_grab()
                self.start_pos = self.current_pos
                self.state = State.FORWARD_SCAN

        elif self.state == State.FORWARD_SCAN:
            if self.current_pos - self.start_pos >= self.target_distance:
                self.serial.send("P")
                self.cam.stop_grab()
                img = self.cam.stitch()
                if img is not None and self.save_path:
                    cv2.imwrite(os.path.join(self.save_path, "forward.jpg"), img)
                self.state = State.SAVE_FORWARD

        elif self.state == State.SAVE_FORWARD:
            self.serial.send("B")
            self.cam.start_grab()
            self.start_pos = self.current_pos
            self.state = State.BACKWARD_SCAN

        elif self.state == State.BACKWARD_SCAN:
            if self.start_pos - self.current_pos >= self.target_distance:
                self.serial.send("P")
                self.cam.stop_grab()
                img = self.cam.stitch()
                if img is not None and self.save_path:
                    img = cv2.flip(img, 0)
                    cv2.imwrite(os.path.join(self.save_path, "backward.jpg"), img)
                self.state = State.SAVE_BACKWARD

        elif self.state == State.SAVE_BACKWARD:
            self.serial.send("GO")
            self.state = State.WAIT_QR

# =========================
# ui.py
# =========================
from PyQt5.QtWidgets import *
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap
import cv2
import numpy as np

from test.camera import CameraThread
from serial_ctrl import SerialController
from controller import Controller
from state_machine import State

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("线阵扫描系统")
        self.setFixedSize(900, 700)

        self.label_img = QLabel()
        self.label_img.setFixedSize(860, 480)
        self.label_img.setStyleSheet("background-color: #222; border: 1px solid #666;")

        self.btn_qr = QPushButton("模拟二维码触发")
        self.btn_path = QPushButton("选择保存路径")
        self.label_state = QLabel("当前状态：等待二维码")

        layout = QVBoxLayout()
        layout.addWidget(self.label_img)
        layout.addWidget(self.btn_qr)
        layout.addWidget(self.btn_path)
        layout.addWidget(self.label_state)
        self.setLayout(layout)

        self.qr_flag = False
        self.save_path = ""

        try:
            self.cam = CameraThread()
            self.cam.open()
            self.cam.start()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"相机异常：{str(e)}")
            return

        self.serial = SerialController()
        self.ctrl = Controller(self.cam, self.serial)

        self.btn_qr.clicked.connect(self.trigger_qr)
        self.btn_path.clicked.connect(self.select_save_path)

        self.timer = QTimer()
        self.timer.timeout.connect(self.loop)
        self.timer.start(40)

    def trigger_qr(self):
        self.qr_flag = True

    def select_save_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存文件夹")
        if path:
            self.save_path = path
            self.ctrl.set_save_path(path)
            self.label_state.setText(f"路径已设置：{path}")

    def loop(self):
        self.ctrl.update(self.qr_flag)
        self.qr_flag = False

        state_map = {
            State.WAIT_QR: "等待二维码",
            State.STOP_CAR: "已停车",
            State.FORWARD_SCAN: "正向扫描中",
            State.SAVE_FORWARD: "保存正向图像",
            State.BACKWARD_SCAN: "反向扫描中",
            State.SAVE_BACKWARD: "保存反向图像"
        }
        self.label_state.setText(f"状态：{state_map[self.ctrl.state]}")

        img = self.cam.get_current_image()
        if img is not None:
            h, w = img.shape[:2]
            if len(img.shape) == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                q_img = QImage(img.data, w, h, 3*w, QImage.Format_RGB888)
            else:
                q_img = QImage(img.data, w, h, w, QImage.Format_Grayscale8)
            self.label_img.setPixmap(QPixmap.fromImage(q_img).scaled(
                self.label_img.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))