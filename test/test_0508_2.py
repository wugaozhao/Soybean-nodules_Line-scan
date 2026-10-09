import sys
import os
import time
import datetime
import ctypes               # 补充缺失的导入
import cv2
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QGridLayout, QVBoxLayout,
                             QGroupBox, QComboBox, QPushButton, QLabel, QLineEdit,
                             QRadioButton, QButtonGroup, QPlainTextEdit, QMessageBox, QHBoxLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QMutex
from PyQt5.QtGui import QImage, QPixmap
import serial
import serial.tools.list_ports

# ===================== 相机SDK配置 =====================
MV_SDK_PATH = r"D:\MVS\MVS\Development\Samples\Python\MvImport"
sys.path.append(MV_SDK_PATH)
try:
    from MvImport.MvCameraControl_class import *
    SDK_LOADED = True
except:
    SDK_LOADED = False

PIXEL_SIZE = 0.021          # mm
LEAD_SCREW = 5.0            # mm
STEPS_PER_REV = 200
# ======================================================

class SerialThread(QThread):
    log_signal = pyqtSignal(str)
    data_signal = pyqtSignal(str, str)

    def __init__(self, port_id, port_name):
        super().__init__()
        self.port_id = port_id
        self.port_name = port_name
        self.ser = None
        self.running = False

    def run(self):
        try:
            self.ser = serial.Serial(self.port_name, 115200, timeout=0.1)
            self.running = True
            self.log_signal.emit(f"[{self.port_id}] 连接成功")
            while self.running:
                if self.ser.in_waiting:
                    data = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    if data:
                        self.data_signal.emit(self.port_id, data)
                time.sleep(0.005)
        except:
            self.log_signal.emit(f"[{self.port_id}] 连接失败")

    def send_cmd(self, cmd):
        if self.ser and self.ser.is_open:
            self.ser.write((cmd + '\n').encode())
            self.log_signal.emit(f"[{self.port_id}] → {cmd}")

    def stop(self):
        self.running = False
        if self.ser: self.ser.close()

class LineScanCameraThread(QThread):
    log_signal = pyqtSignal(str)
    frame_signal = pyqtSignal(np.ndarray)
    camera_ready = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.cam = None
        self.running = False
        self.line_rate = 1000      # 默认值，后续通过 update_line_rate 修改
        self.trigger_mode = 0
        self.current_frame = None
        self.frame_lock = QMutex()

    def init_camera(self):
        if not SDK_LOADED:
            self.log_signal.emit("未加载相机SDK")
            return False
        try:
            self.cam = MvCamera()
            dev_list = MV_CC_DEVICE_INFO_LIST()
            MvCamera.MV_CC_EnumDevices(MV_USB_DEVICE | MV_GIGE_DEVICE, dev_list)
            if dev_list.nDeviceNum == 0:
                self.log_signal.emit("未找到相机")
                return False

            self.cam.MV_CC_CreateHandle(dev_list.pDeviceInfo[0])
            self.cam.MV_CC_OpenDevice()
            self.cam.MV_CC_SetEnumValue("PixelFormat", 0x10800001)   # Mono8
            self.cam.MV_CC_SetFloatValue("ExposureTime", 35000.0)
            self.cam.MV_CC_SetEnumValue("BalanceWhiteAuto", 2)      # Once
            self.cam.MV_CC_SetEnumValue("AcquisitionMode", 2)       # Continuous
            # 行频在 update_line_rate 中设置，此处先不设
            self.log_signal.emit("线扫相机初始化成功")
            return True
        except Exception as e:
            self.log_signal.emit(f"相机初始化失败：{str(e)}")
            return False

    def set_trigger_soft(self):
        self.trigger_mode = 0
        if self.cam:
            self.cam.MV_CC_SetEnumValue("TriggerMode", 0)

    def set_trigger_hard(self):
        self.trigger_mode = 1
        if self.cam:
            self.cam.MV_CC_SetEnumValue("TriggerMode", 1)
            self.cam.MV_CC_SetEnumValue("TriggerSource", 0)

    def update_line_rate(self, motor_freq, subdivision):
        # 修正后的行频公式
        self.line_rate = int(motor_freq * LEAD_SCREW / (STEPS_PER_REV * subdivision * PIXEL_SIZE))
        if self.cam:
            self.cam.MV_CC_SetFloatValue("LineRate", self.line_rate)
        self.log_signal.emit(f"行频已同步（相机轴）：{self.line_rate} Hz")

    def get_current_frame(self):
        self.frame_lock.lock()
        frame = self.current_frame.copy() if self.current_frame is not None else None
        self.frame_lock.unlock()
        return frame

    def run(self):
        if not self.init_camera():
            return
        self.running = True
        self.cam.MV_CC_StartGrabbing()
        self.log_signal.emit("线扫相机开始采集")
        self.camera_ready.emit()

        while self.running:
            stFrame = MV_FRAME_OUT()
            ret = self.cam.MV_CC_GetOneFrameTimeout(stFrame, 1000)
            if ret == 0:
                img_buf = (ctypes.c_ubyte * stFrame.stFrameInfo.nWidth * stFrame.stFrameInfo.nHeight).from_address(
                    ctypes.addressof(stFrame.pBufAddr.contents))
                img = np.array(img_buf).reshape(stFrame.stFrameInfo.nHeight, stFrame.stFrameInfo.nWidth)
                self.frame_lock.lock()
                self.current_frame = img.copy()
                self.frame_lock.unlock()
                self.frame_signal.emit(img)
            time.sleep(0.02)

        self.cam.MV_CC_StopGrabbing()
        self.cam.MV_CC_CloseDevice()
        self.log_signal.emit("相机已停止")

    def stop(self):
        self.running = False

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("线扫相机运动控制系统")
        self.setGeometry(100, 100, 1300, 800)

        self.serials = {"A": None, "B": None, "Scanner": None}
        self.cam_thread = None
        self.cam_ready = False
        self.scan_processing = False
        self.last_car_direction = 0
        self.current_qr = ""
        self._waiting_B_return = False

        self.init_ui()
        self.make_save_dir()

    # ---------- 界面 ----------
    def init_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        main = QGridLayout(cw)

        # ---- 串口 ----
        g1 = QGroupBox("串口连接")
        l1 = QGridLayout()
        l1.addWidget(QLabel("电机A串口"), 0, 0)
        self.cbA = QComboBox()
        l1.addWidget(self.cbA, 0, 1)
        l1.addWidget(QLabel("电机B串口"), 1, 0)
        self.cbB = QComboBox()
        l1.addWidget(self.cbB, 1, 1)
        l1.addWidget(QLabel("扫码器串口"), 2, 0)
        self.cbScan = QComboBox()
        l1.addWidget(self.cbScan, 2, 1)

        hbtn = QHBoxLayout()
        self.btn_ref = QPushButton("刷新")
        self.btn_con = QPushButton("连接")
        self.btn_dis = QPushButton("断开")
        hbtn.addWidget(self.btn_ref)
        hbtn.addWidget(self.btn_con)
        hbtn.addWidget(self.btn_dis)
        l1.addLayout(hbtn, 3, 0, 1, 2)
        g1.setLayout(l1)
        main.addWidget(g1, 0, 0)

        # ---- 相机参数 ----
        g3 = QGroupBox("线扫相机参数")
        l3 = QGridLayout()
        l3.addWidget(QLabel("曝光时间"), 0, 0)
        self.ed_exp = QLineEdit("35000")
        l3.addWidget(self.ed_exp, 0, 1)
        l3.addWidget(QLabel("白平衡"), 1, 0)
        self.cb_wb = QComboBox()
        self.cb_wb.addItems(["Off", "Once", "Continuous"])
        self.cb_wb.setCurrentIndex(1)
        l3.addWidget(self.cb_wb, 1, 1)

        l3.addWidget(QLabel("触发模式"), 2, 0)
        self.t_soft = QRadioButton("软触发(自动行频)")
        self.t_hard = QRadioButton("硬触发")
        self.t_soft.setChecked(True)
        l3.addWidget(self.t_soft, 2, 1)
        l3.addWidget(self.t_hard, 3, 1)

        self.btn_cam_on = QPushButton("开启相机")
        self.btn_cam_off = QPushButton("关闭相机")
        l3.addWidget(self.btn_cam_on, 4, 0)
        l3.addWidget(self.btn_cam_off, 4, 1)
        g3.setLayout(l3)
        main.addWidget(g3, 0, 1)

        # ---- 双电机控制 ----
        left_bottom = QWidget()
        lb_layout = QVBoxLayout(left_bottom)

        # 小车电机
        g_car = QGroupBox("小车电机控制")
        l_car = QGridLayout()
        l_car.addWidget(QLabel("脉冲频率"), 0, 0)
        self.car_freq = QLineEdit("1000")
        l_car.addWidget(self.car_freq, 0, 1)
        l_car.addWidget(QLabel("脉冲数"), 1, 0)
        self.car_pulse = QLineEdit("10000")
        l_car.addWidget(self.car_pulse, 1, 1)
        l_car.addWidget(QLabel("细分数"), 2, 0)
        self.car_sub = QLineEdit("16")
        l_car.addWidget(self.car_sub, 2, 1)
        l_car.addWidget(QLabel("加速步数"), 3, 0)
        self.car_acc = QLineEdit("2000")
        l_car.addWidget(self.car_acc, 3, 1)

        self.car_fwd = QRadioButton("前进")
        self.car_bwd = QRadioButton("后退")
        self.car_fwd.setChecked(True)
        car_dir = QHBoxLayout()
        car_dir.addWidget(self.car_fwd)
        car_dir.addWidget(self.car_bwd)
        l_car.addLayout(car_dir, 4, 0, 1, 2)

        self.btn_car_run = QPushButton("启动小车")
        self.btn_car_stop = QPushButton("停止小车")
        l_car.addWidget(self.btn_car_run, 5, 0, 1, 2)
        l_car.addWidget(self.btn_car_stop, 6, 0, 1, 2)
        g_car.setLayout(l_car)
        lb_layout.addWidget(g_car)

        # 相机轴电机
        g_cam = QGroupBox("相机轴电机控制")
        l_cam = QGridLayout()
        l_cam.addWidget(QLabel("脉冲频率"), 0, 0)
        self.cam_freq = QLineEdit("1000")
        l_cam.addWidget(self.cam_freq, 0, 1)
        l_cam.addWidget(QLabel("脉冲数"), 1, 0)
        self.cam_pulse = QLineEdit("10000")
        l_cam.addWidget(self.cam_pulse, 1, 1)
        l_cam.addWidget(QLabel("细分数"), 2, 0)
        self.cam_sub = QLineEdit("16")
        l_cam.addWidget(self.cam_sub, 2, 1)
        l_cam.addWidget(QLabel("加速步数"), 3, 0)
        self.cam_acc = QLineEdit("2000")
        l_cam.addWidget(self.cam_acc, 3, 1)

        self.cam_fwd = QRadioButton("正向")
        self.cam_bwd = QRadioButton("反向")
        self.cam_fwd.setChecked(True)
        cam_dir = QHBoxLayout()
        cam_dir.addWidget(self.cam_fwd)
        cam_dir.addWidget(self.cam_bwd)
        l_cam.addLayout(cam_dir, 4, 0, 1, 2)

        self.btn_cam_run = QPushButton("启动相机轴")
        self.btn_cam_stop = QPushButton("停止相机轴")
        l_cam.addWidget(self.btn_cam_run, 5, 0, 1, 2)
        l_cam.addWidget(self.btn_cam_stop, 6, 0, 1, 2)
        g_cam.setLayout(l_cam)
        lb_layout.addWidget(g_cam)

        main.addWidget(left_bottom, 1, 0)

        # ---- 图像预览 ----
        g4 = QGroupBox("线扫图像预览")
        l4 = QGridLayout()
        self.img_label = QLabel("线扫相机未启动")
        self.img_label.setStyleSheet("background-color:#222;color:white")
        self.img_label.setAlignment(Qt.AlignCenter)
        l4.addWidget(self.img_label)
        g4.setLayout(l4)
        main.addWidget(g4, 1, 1)

        # ---- 日志 ----
        g5 = QGroupBox("系统日志")
        l5 = QGridLayout()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        l5.addWidget(self.log)
        g5.setLayout(l5)
        main.addWidget(g5, 2, 0, 1, 2)

        # 信号绑定
        self.btn_ref.clicked.connect(self.refresh_ports)
        self.btn_con.clicked.connect(self.connect_all)
        self.btn_dis.clicked.connect(self.disconnect_all)
        self.btn_car_run.clicked.connect(self.run_car)
        self.btn_car_stop.clicked.connect(lambda: self.stop_motor("A"))
        self.btn_cam_run.clicked.connect(self.run_cam_axis)
        self.btn_cam_stop.clicked.connect(lambda: self.stop_motor("B"))
        self.btn_cam_on.clicked.connect(self.start_camera)
        self.btn_cam_off.clicked.connect(self.stop_camera)
        self.refresh_ports()

    # ---------- 工具方法 ----------
    def make_save_dir(self):
        path = f"D:/Date{datetime.datetime.now().strftime('%m%d')}"
        if not os.path.exists(path):
            os.makedirs(path)
        self.save_path = path
        self.logs(f"保存路径：{path}")

    def refresh_ports(self):
        self.cbA.clear()
        self.cbB.clear()
        self.cbScan.clear()
        for p in serial.tools.list_ports.comports():
            self.cbA.addItem(p.device, p.device)
            self.cbB.addItem(p.device, p.device)
            self.cbScan.addItem(p.device, p.device)

    def connect_all(self):
        for mid, cb in [("A", self.cbA), ("B", self.cbB), ("Scanner", self.cbScan)]:
            port = cb.currentData()
            if port:
                t = SerialThread(mid, port)
                t.log_signal.connect(self.logs)
                t.data_signal.connect(self.on_serial_data)
                t.start()
                self.serials[mid] = t

    def disconnect_all(self):
        for t in self.serials.values():
            if t: t.stop()
        self.stop_camera()

    def logs(self, msg):
        self.log.appendPlainText(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

    # ---------- 电机控制 ----------
    def run_car(self):
        t = self.serials["A"]
        if not t:
            QMessageBox.warning(self, "警告", "请先连接串口")
            return
        if self.scan_processing:
            self.logs("正在处理扫码，忽略启动")
            return
        self.last_car_direction = 0 if self.car_fwd.isChecked() else 1
        t.send_cmd(f"F:{self.car_freq.text()}")
        t.send_cmd(f"N:{self.car_pulse.text()}")
        t.send_cmd(f"D:{self.last_car_direction}")
        t.send_cmd(f"A:{self.car_acc.text()}")
        t.send_cmd("S")

    def stop_motor(self, mid):
        if self.serials[mid]:
            self.serials[mid].send_cmd("T")

    def run_cam_axis(self):
        t = self.serials["B"]
        if not t:
            QMessageBox.warning(self, "警告", "请先连接相机轴串口")
            return
        if self.t_soft.isChecked() and self.cam_thread and self.cam_ready:
            self.cam_thread.update_line_rate(int(self.cam_freq.text()), int(self.cam_sub.text()))
        dir_val = 0 if self.cam_fwd.isChecked() else 1
        t.send_cmd(f"F:{self.cam_freq.text()}")
        t.send_cmd(f"N:{self.cam_pulse.text()}")
        t.send_cmd(f"D:{dir_val}")
        t.send_cmd(f"A:{self.cam_acc.text()}")
        t.send_cmd("S")

    # ---------- 相机 ----------
    def start_camera(self):
        if self.cam_thread and self.cam_thread.isRunning():
            self.logs("相机已运行")
            return
        self.cam_thread = LineScanCameraThread()
        self.cam_thread.log_signal.connect(self.logs)
        self.cam_thread.frame_signal.connect(self.show_img)
        self.cam_thread.camera_ready.connect(self.on_camera_ready)
        if self.t_soft.isChecked():
            self.cam_thread.set_trigger_soft()
        else:
            self.cam_thread.set_trigger_hard()
        self.cam_thread.start()

    def stop_camera(self):
        if self.cam_thread:
            self.cam_thread.stop()
            self.cam_thread.wait()
            self.cam_thread = None
            self.cam_ready = False

    def on_camera_ready(self):
        self.cam_ready = True
        if self.t_soft.isChecked():
            self.cam_thread.update_line_rate(int(self.cam_freq.text()), int(self.cam_sub.text()))

    def show_img(self, img):
        img = np.ascontiguousarray(img)
        h, w = img.shape
        qimg = QImage(img.data, w, h, w, QImage.Format_Grayscale8)
        self.img_label.setPixmap(QPixmap.fromImage(qimg).scaled(
            self.img_label.size(), Qt.KeepAspectRatio))

    # ---------- 扫码自动流程 ----------
    def on_serial_data(self, port, data):
        self.logs(f"[{port}] {data}")
        if port == "Scanner" and data.startswith("QR:") and not self.scan_processing:
            qr = data[3:].strip()
            if qr:
                self.start_scan_process(qr)
        if port == "B" and data == "DONE":
            self.on_motor_B_done()

    def start_scan_process(self, qr):
        if self.scan_processing:
            return
        self.scan_processing = True
        self.current_qr = qr
        self.logs(f"扫码：{qr} → 停止小车")
        self.stop_motor("A")

        # 确保相机启动（复用已有线程）
        if self.cam_thread and self.cam_thread.isRunning():
            if self.cam_ready:
                self._start_motor_B()
            else:
                # 相机正在初始化，等待就绪信号
                self.cam_thread.camera_ready.connect(self._start_motor_B)
        else:
            # 没有相机线程，创建并启动
            self.cam_thread = LineScanCameraThread()
            self.cam_thread.log_signal.connect(self.logs)
            self.cam_thread.frame_signal.connect(self.show_img)
            self.cam_thread.camera_ready.connect(self.on_camera_ready)
            self.cam_thread.camera_ready.connect(self._start_motor_B)  # 就绪后直接启动电机B
            if self.t_soft.isChecked():
                self.cam_thread.set_trigger_soft()
            else:
                self.cam_thread.set_trigger_hard()
            self.cam_thread.start()

    def _start_motor_B(self):
        # 二次确认，避免重复调用
        if not self.scan_processing or self._waiting_B_return:
            return
        t = self.serials["B"]
        if not t:
            self.logs("错误：相机轴串口未连接")
            self.scan_processing = False
            return
        self.logs("启动相机轴正向运动")
        if self.t_soft.isChecked() and self.cam_thread and self.cam_ready:
            self.cam_thread.update_line_rate(int(self.cam_freq.text()), int(self.cam_sub.text()))
        t.send_cmd(f"F:{self.cam_freq.text()}")
        t.send_cmd(f"N:{self.cam_pulse.text()}")
        t.send_cmd("D:0")
        t.send_cmd(f"A:{self.cam_acc.text()}")
        t.send_cmd("S")

    def on_motor_B_done(self):
        if not self.scan_processing:
            return
        if not self._waiting_B_return:
            # 正向运动完成 → 保存图像并开始回零
            self.logs("相机轴正向运动完成，保存图像")
            frame = self.cam_thread.get_current_frame() if self.cam_thread else None
            if frame is not None:
                cv2.imwrite(f"{self.save_path}/{self.current_qr}.bmp", frame)
                self.logs("图像保存成功")
            else:
                self.logs("错误：未获取到图像")
            self.logs("相机轴回零")
            self._waiting_B_return = True
            t = self.serials["B"]
            t.send_cmd(f"F:{self.cam_freq.text()}")
            t.send_cmd(f"N:{self.cam_pulse.text()}")
            t.send_cmd("D:1")
            t.send_cmd(f"A:{self.cam_acc.text()}")
            t.send_cmd("S")
        else:
            # 回零完成 → 恢复小车运动
            self.logs("回零完成 → 继续小车")
            self._waiting_B_return = False
            self.scan_processing = False
            t = self.serials["A"]
            if t:
                t.send_cmd(f"F:{self.car_freq.text()}")
                t.send_cmd(f"N:{self.car_pulse.text()}")
                t.send_cmd(f"D:{self.last_car_direction}")
                t.send_cmd(f"A:{self.car_acc.text()}")
                t.send_cmd("S")

    def closeEvent(self, e):
        self.disconnect_all()
        e.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())