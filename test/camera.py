# -*- coding: utf-8 -*-
import sys
import os
import platform
import ctypes
from ctypes import (memset, c_ubyte, byref, cast, POINTER, sizeof, c_void_p)
from datetime import datetime
import traceback

import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QLineEdit,
                             QGroupBox, QFormLayout, QTextEdit, QFileDialog,
                             QInputDialog)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QMutex, QMutexLocker
from PyQt5.QtGui import QImage, QPixmap

# ===================== SDK路径配置 =====================
MV_SDK_PATH = os.getenv("MV_SDK_PATH", r"D:\MVS\MVS\Development\Samples\Python\MvImport")
if MV_SDK_PATH not in sys.path:
    sys.path.append(MV_SDK_PATH)

currentsystem = platform.system()
if currentsystem == 'Windows':
    MVCAM_PATH = os.getenv('MVCAM_COMMON_RUNENV')
    if MVCAM_PATH and os.path.exists(os.path.join(MVCAM_PATH, "Samples", "Python", "MvImport")):
        sys.path.append(os.path.join(MVCAM_PATH, "Samples", "Python", "MvImport"))
else:
    sys.path.append(os.path.join("../..", "..", "MvImport"))

# 导入SDK
try:
    from MvCameraControl_class import *
except Exception as e:
    print(f"导入MvCameraControl_class失败: {e}")
    traceback.print_exc()
    sys.exit(1)

# ===================== 全局工具函数 =====================
def decoding_char(ctypes_char_array):
    """安全地从ctypes字符数组中解码出字符串"""
    try:
        byte_str = memoryview(ctypes_char_array).tobytes()
        null_index = byte_str.find(b'\x00')
        if null_index != -1:
            byte_str = byte_str[:null_index]
        for encoding in ['gbk', 'utf-8', 'latin-1']:
            try:
                return byte_str.decode(encoding)
            except UnicodeDecodeError:
                continue
        return byte_str.decode('latin-1', errors='replace')
    except Exception as e:
        print(f"解码字符失败: {e}")
        return "Unknown"

# ===================== 相机取流线程 =====================
class CameraThread(QThread):
    image_update = pyqtSignal(object)
    frame_received = pyqtSignal(np.ndarray)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.mutex = QMutex()
        self.cam = None
        self.is_grabbing = False
        self.is_running = False
        self.image_width = 0
        self.image_height = 0
        self.nPayloadSize = 0

    def set_line_scan_params(self, line_frequency=2000):
        if self.cam is None:
            self.log_signal.emit("错误: 相机未初始化")
            return False
        try:
            ret = self.cam.MV_CC_SetEnumValue("LineTriggerMode", 1)
            if ret == 0:
                self.log_signal.emit("行触发模式设置为: 内部行触发")
            else:
                self.log_signal.emit(f"设置行触发模式失败: 0x{ret:X}")
                return False

            ret = self.cam.MV_CC_SetIntValue("LineFrequency", int(line_frequency))
            if ret == 0:
                self.log_signal.emit(f"行频设置成功: {line_frequency} Hz")
            else:
                self.log_signal.emit(f"设置行频失败: 0x{ret:X}")
                return False

            ret = self.cam.MV_CC_SetBoolValue("SelfTrigger", True)
            if ret == 0:
                self.log_signal.emit("自触发已开启")
            else:
                self.log_signal.emit(f"开启自触发失败: 0x{ret:X}")

            ret = self.cam.MV_CC_SetEnumValue("TransmitMode", 1)
            if ret == 0:
                self.log_signal.emit("传输模式设置为: 块传输")
            else:
                self.log_signal.emit(f"设置传输模式失败: 0x{ret:X}")

            ret = self.cam.MV_CC_SetBoolValue("Correct", True)
            if ret == 0:
                self.log_signal.emit("图像校正已开启")
            else:
                self.log_signal.emit(f"开启图像校正失败: 0x{ret:X}")
            return True
        except Exception as e:
            self.log_signal.emit(f"设置线扫参数异常: {str(e)}")
            traceback.print_exc()
            return False

    def set_trigger_mode(self):
        if self.cam is None:
            self.log_signal.emit("错误: 相机未初始化")
            return False
        try:
            ret = self.cam.MV_CC_SetEnumValue("FrameTriggerMode", 2)
            if ret == 0:
                self.log_signal.emit("帧触发模式设置为: EventOnly")
            else:
                self.log_signal.emit(f"设置帧触发模式失败: 0x{ret:X},切换连续触发")
                ret = self.cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
                if ret != 0:
                    return False
                self.log_signal.emit("触发模式设置为: 连续采集")
            return True
        except Exception as e:
            self.log_signal.emit(f"设置触发模式异常: {str(e)}")
            traceback.print_exc()
            return False

    def init_camera(self, device_index=0):
        try:
            self.log_signal.emit("正在初始化SDK...")
            try:
                MvCamera.MV_CC_Initialize()
            except Exception as e:
                self.log_signal.emit(f"SDK初始化失败: {str(e)}")
                return False

            deviceList = MV_CC_DEVICE_INFO_LIST()
            t_layer_type = (MV_GIGE_DEVICE | MV_USB_DEVICE | MV_GENTL_CAMERALINK_DEVICE
                            | MV_GENTL_CXP_DEVICE | MV_GENTL_XOF_DEVICE)

            ret = MvCamera.MV_CC_EnumDevices(t_layer_type, deviceList)
            if ret != 0:
                self.log_signal.emit(f"枚举设备失败: 0x{ret:X}")
                return False

            if deviceList.nDeviceNum == 0:
                self.log_signal.emit("未找到任何设备!")
                return False
            self.log_signal.emit(f"找到 {deviceList.nDeviceNum} 个设备")

            for i in range(deviceList.nDeviceNum):
                mvcc_dev_info = cast(deviceList.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
                if mvcc_dev_info.nTLayerType == MV_GIGE_DEVICE:
                    strModeName = decoding_char(mvcc_dev_info.SpecialInfo.stGigEInfo.chModelName)
                    strSerialNumber = decoding_char(mvcc_dev_info.SpecialInfo.stGigEInfo.chSerialNumber)
                    self.log_signal.emit(f"设备[{i}]: {strModeName} (SN: {strSerialNumber})")
                elif mvcc_dev_info.nTLayerType == MV_USB_DEVICE:
                    strModeName = decoding_char(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chModelName)
                    strSerialNumber = decoding_char(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber)
                    self.log_signal.emit(f"设备[{i}]: {strModeName} (SN: {strSerialNumber})")

            if device_index >= deviceList.nDeviceNum:
                self.log_signal.emit("设备索引超出范围")
                return False

            self.cam = MvCamera()
            stDeviceList = cast(deviceList.pDeviceInfo[device_index], POINTER(MV_CC_DEVICE_INFO)).contents
            ret = self.cam.MV_CC_CreateHandle(stDeviceList)
            if ret != 0:
                self.log_signal.emit(f"创建句柄失败: 0x{ret:X}")
                return False

            ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
            if ret != 0:
                self.log_signal.emit(f"打开设备失败: 0x{ret:X}")
                return False

            stParam = MVCC_INTVALUE()
            memset(byref(stParam), 0, sizeof(MVCC_INTVALUE))
            ret = self.cam.MV_CC_GetIntValue("Width", stParam)
            if ret == 0:
                self.image_width = stParam.nCurValue

            memset(byref(stParam), 0, sizeof(MVCC_INTVALUE))
            ret = self.cam.MV_CC_GetIntValue("Height", stParam)
            if ret == 0:
                self.image_height = stParam.nCurValue
            self.log_signal.emit(f"图像尺寸: {self.image_width} x {self.image_height},线扫相机")

            memset(byref(stParam), 0, sizeof(MVCC_INTVALUE))
            ret = self.cam.MV_CC_GetIntValue("PayloadSize", stParam)
            if ret != 0:
                self.log_signal.emit(f"获取PayloadSize失败: 0x{ret:X}")
                return False
            self.nPayloadSize = stParam.nCurValue
            self.log_signal.emit(f"PayloadSize: {self.nPayloadSize}")

            self.set_trigger_mode()
            ret = self.cam.MV_CC_SetEnumValue("AcquisitionMode", MV_ACQ_MODE_CONTINUOUS)
            if ret == 0:
                self.log_signal.emit("采集模式设置为: 连续")
            else:
                self.log_signal.emit(f"设置采集模式失败:0x{ret:X}")

            self.log_signal.emit("相机初始化成功")
            return True
        except Exception as e:
            self.log_signal.emit(f"初始化相机异常: {str(e)}")
            traceback.print_exc()
            return False

    def start_grabbing(self):
        locker = QMutexLocker(self.mutex)
        try:
            if self.cam is None:
                self.log_signal.emit("相机未初始化")
                return False
            self.stop_grabbing()
            if not self.isRunning():
                self.start()
                self.log_signal.emit("取流线程已启动")
            self.cam.MV_CC_ClearImageBuffer()
            ret = self.cam.MV_CC_StartGrabbing()
            if ret != 0:
                self.log_signal.emit(f"开始取流失败: 0x{ret:X}")
                return False
            self.is_grabbing = True
            self.log_signal.emit("开始取流...")
            return True
        except Exception as e:
            self.log_signal.emit(f"开始取流异常: {str(e)}")
            traceback.print_exc()
            return False

    def stop_grabbing(self):
        locker = QMutexLocker(self.mutex)
        try:
            if self.cam is not None and self.is_grabbing:
                ret = self.cam.MV_CC_StopGrabbing()
                if ret != 0:
                    self.log_signal.emit(f"停止取流失败: 0x{ret:X}")
                else:
                    self.log_signal.emit("停止取流")
            self.is_grabbing = False
        except Exception as e:
            self.log_signal.emit(f"停止取流异常: {str(e)}")
            traceback.print_exc()
            self.is_grabbing = False

    def run(self):
        self.is_running = True
        frame_count = 0
        while True:
            locker = QMutexLocker(self.mutex)
            run_flag = self.is_running
            grab_flag = self.is_grabbing
            locker.unlock()
            if not run_flag:
                break
            if not grab_flag or self.cam is None:
                QThread.msleep(10)
                continue

            try:
                stOutFrame = MV_FRAME_OUT()
                memset(byref(stOutFrame), 0, sizeof(stOutFrame))
                ret = self.cam.MV_CC_GetImageBuffer(stOutFrame, 1000)
                if ret == 0 and stOutFrame.pBufAddr is not None:
                    frame_count += 1
                    width = stOutFrame.stFrameInfo.nWidth
                    height = stOutFrame.stFrameInfo.nHeight
                    pixel_type = stOutFrame.stFrameInfo.enPixelType

                    if pixel_type == PixelType_Gvsp_RGB8_Packed:
                        bytes_per_pixel = 3
                    elif pixel_type == PixelType_Gvsp_Mono8:
                        bytes_per_pixel = 1
                    else:
                        bytes_per_pixel = 1
                        if frame_count == 1:
                            self.log_signal.emit(f"不支持的像素格式: 0x{pixel_type:X}，默认按Mono8处理")

                    data = (c_ubyte * (width * height * bytes_per_pixel)).from_address(ctypes.addressof(stOutFrame.pBufAddr.contents))
                    img_array = np.frombuffer(data, dtype=np.uint8).copy()
                    img_array = img_array.reshape((height, width, bytes_per_pixel))

                    self.frame_received.emit(img_array)
                    self.image_update.emit(img_array)

                    if frame_count % 100 == 0:
                        self.log_signal.emit(f"已获取 {frame_count} 帧图像")
                else:
                    if ret != 0x8000000A:
                        self.log_signal.emit(f"获取图像失败: 0x{ret:X}")
            except Exception as e:
                self.log_signal.emit(f"获取图像帧异常: {str(e)}")
                QThread.msleep(100)
            finally:
                try:
                    if 'stOutFrame' in locals():
                        self.cam.MV_CC_FreeImageBuffer(stOutFrame)
                except:
                    pass
        locker = QMutexLocker(self.mutex)
        self.is_grabbing = False
        locker.unlock()
        self.finished_signal.emit()
        self.log_signal.emit(f"取流线程结束，共获取 {frame_count} 帧")

    def cleanup(self):
        locker = QMutexLocker(self.mutex)
        self.is_running = False
        self.is_grabbing = False
        locker.unlock()
        self.stop_grabbing()
        if self.isRunning():
            self.wait(3000)
        try:
            if self.cam:
                self.cam.MV_CC_CloseDevice()
                self.cam.MV_CC_DestroyHandle()
                self.cam = None
            MvCamera.MV_CC_Finalize()
        except Exception as e:
            self.log_signal.emit(f"资源释放异常:{e}")

# ===================== 图像合成类 =====================
class ImageSynthesizer:
    def __init__(self):
        self.reset()

    def reset(self):
        self.frames = []
        self.total_height = 0
        self.width = 0
        self.bytes_per_pixel = 1

    def add_frame(self, img_array):
        if img_array is None or img_array.size == 0:
            return False
        if len(img_array.shape) == 2:
            height, width = img_array.shape
            bytes_per_pixel = 1
            img_reshaped = img_array.reshape(height, width, 1)
        else:
            height, width, bytes_per_pixel = img_array.shape
        if self.total_height == 0:
            self.width = width
            self.bytes_per_pixel = bytes_per_pixel
        if width != self.width:
            return False
        self.frames.append(img_array)
        self.total_height += height
        return True

    def get_combined_image(self):
        if not self.frames:
            return None
        combined = np.vstack(self.frames)
        if combined.shape[-1] == 1:
            combined = combined.squeeze(axis=-1)
        return combined

    def get_frame_count(self):
        return len(self.frames)

    def get_total_height(self):
        return self.total_height

# ===================== 主窗口 =====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.camera_thread = None
        self.synthesizer = ImageSynthesizer()
        self.is_capturing = False
        self.current_file_name = ""
        self.save_dir = os.path.join(os.path.expanduser("~"), "Desktop", "CameraImages")
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("线扫描相机控制系统")
        self.setGeometry(100, 100, 1200, 800)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 左侧面板
        left_panel = QWidget()
        left_panel.setFixedWidth(300)
        left_layout = QVBoxLayout(left_panel)

        param_group = QGroupBox("相机参数")
        param_layout = QFormLayout()
        self.line_frequency_input = QLineEdit("2000")
        param_layout.addRow("行频(Hz):", self.line_frequency_input)
        self.apply_params_btn = QPushButton("应用参数")
        self.apply_params_btn.clicked.connect(self.apply_params)
        param_group.setLayout(param_layout)
        left_layout.addWidget(param_group)

        save_group = QGroupBox("保存设置")
        save_layout = QVBoxLayout()
        self.save_path_label = QLabel(f"当前路径:\n{self.save_dir}")
        self.save_path_label.setWordWrap(True)
        self.select_path_btn = QPushButton("选择保存路径")
        self.select_path_btn.clicked.connect(self.select_save_path)
        save_layout.addWidget(self.save_path_label)
        save_layout.addWidget(self.select_path_btn)
        save_group.setLayout(save_layout)
        left_layout.addWidget(save_group)

        control_group = QGroupBox("相机控制")
        control_layout = QVBoxLayout()
        self.init_cam_btn = QPushButton("初始化相机")
        self.init_cam_btn.clicked.connect(self.init_camera)
        self.start_btn = QPushButton("开始拍摄")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_capture)
        self.stop_btn = QPushButton("停止拍摄")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_capture)
        control_layout.addWidget(self.init_cam_btn)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_group.setLayout(control_layout)
        left_layout.addWidget(control_group)

        info_group = QGroupBox("设备信息")
        info_layout = QVBoxLayout()
        self.info_label = QLabel("未初始化")
        self.info_label.setWordWrap(True)
        info_layout.addWidget(self.info_label)
        info_group.setLayout(info_layout)
        left_layout.addWidget(info_group)
        left_layout.addStretch()

        # 右侧预览
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        preview_group = QGroupBox("图像预览")
        preview_layout = QVBoxLayout()
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background-color: black; color: white;")
        self.preview_label.setMinimumSize(640, 480)
        self.preview_label.setText("等待图像...")
        preview_layout.addWidget(self.preview_label)
        preview_group.setLayout(preview_layout)
        right_layout.addWidget(preview_group)

        log_group = QGroupBox("日志信息")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group)

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1)

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def select_save_path(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择保存路径", self.save_dir)
        if dir_path:
            self.save_dir = dir_path
            self.save_path_label.setText(f"当前路径:\n{self.save_dir}")
            self.log(f"保存路径已更改为: {self.save_dir}")

    def init_camera(self):
        self.log("正在初始化相机...")
        if self.camera_thread is not None:
            self.camera_thread.cleanup()
            self.camera_thread = None
        self.camera_thread = CameraThread()
        self.camera_thread.log_signal.connect(self.log)
        self.camera_thread.image_update.connect(self.update_preview)
        self.camera_thread.frame_received.connect(self.on_frame_received)
        if self.camera_thread.init_camera(device_index=0):
            self.start_btn.setEnabled(True)
            self.info_label.setText("相机已就绪")
            self.log("相机初始化成功")
        else:
            self.start_btn.setEnabled(False)
            self.info_label.setText("相机初始化失败")
            self.camera_thread = None

    def apply_params(self):
        if self.camera_thread is None:
            self.log("请先初始化相机")
            return
        if self.is_capturing:
            self.log("拍摄中，请先停止拍摄再修改参数")
            return
        try:
            line_frequency = int(self.line_frequency_input.text())
            if self.camera_thread.set_line_scan_params(line_frequency):
                self.log("所有参数设置完成")
            else:
                self.log("部分参数设置失败")
        except ValueError:
            self.log("行频值错误: 请输入整数")

    def start_capture(self):
        if self.camera_thread is None:
            self.log("请先初始化相机")
            return
        if self.is_capturing:
            self.log("已在拍摄中")
            return
        file_name, ok = QInputDialog.getText(self, "保存文件名", "请输入文件名（不含扩展名）:")
        if not ok or not file_name.strip():
            self.log("未输入文件名，取消拍摄")
            return
        self.current_file_name = file_name.strip()
        self.synthesizer = ImageSynthesizer()
        self.apply_params()
        if self.camera_thread.start_grabbing():
            self.is_capturing = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.init_cam_btn.setEnabled(False)
            self.log(f"开始拍摄，文件名: {self.current_file_name}")
        else:
            self.is_capturing = False

    def stop_capture(self):
        if not self.is_capturing:
            return
        self.log("正在停止拍摄...")
        if self.camera_thread is not None:
            self.camera_thread.stop_grabbing()
        self.is_capturing = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.init_cam_btn.setEnabled(True)
        self.save_combined_image()

    def on_frame_received(self, img_array):
        if self.is_capturing and img_array is not None:
            self.synthesizer.add_frame(img_array)
            cnt = self.synthesizer.get_frame_count()
            if cnt % 100 == 0:
                self.log(f"已接收 {cnt} 帧，合成高度: {self.synthesizer.get_total_height()}")

    def update_preview(self, img_array):
        if img_array is None:
            return
        if len(img_array.shape) == 3:
            h,w,c = img_array.shape
            if c ==3:
                qimg = QImage(img_array.data, w, h, w*3, QImage.Format_RGB888)
            else:
                qimg = QImage(img_array.data, w, h, w, QImage.Format_Grayscale8)
        else:
            h,w = img_array.shape
            qimg = QImage(img_array.data, w, h, w, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(qimg)
        scaled_pix = pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(scaled_pix)

    def save_combined_image(self):
        combined_img = self.synthesizer.get_combined_image()
        if combined_img is None:
            self.log("没有接收到任何图像数据")
            return
        date_folder = datetime.now().strftime("%Y%m%d")
        save_path = os.path.join(self.save_dir, date_folder)
        if not os.path.exists(save_path):
            os.makedirs(save_path)
        try:
            from PIL import Image
            if len(combined_img.shape) ==2:
                img = Image.fromarray(combined_img, "L")
            else:
                img = Image.fromarray(combined_img, "RGB")
            full = os.path.join(save_path, f"{self.current_file_name}.bmp")
            img.save(full)
            cnt = self.synthesizer.get_frame_count()
            h_total = self.synthesizer.get_total_height()
            self.log(f"图像已保存:{full},总帧数:{cnt},尺寸{combined_img.shape[1]}×{h_total}")
            self.info_label.setText(f"已保存:{self.current_file_name}.bmp\n{combined_img.shape[1]}×{h_total}")
        except ImportError:
            self.log("缺少Pillow: pip install pillow")
        except Exception as e:
            self.log(f"保存失败:{e}")

    def closeEvent(self, event):
        self.log("正在关闭程序...")
        if self.camera_thread is not None:
            self.camera_thread.cleanup()
        event.accept()

# ===================== 程序入口 =====================
def main():
    # 前置校验Pillow
    try:
        from PIL import Image
    except ImportError:
        print("缺失依赖库，请执行：pip install pyqt5 numpy pillow")
        sys.exit(1)
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()