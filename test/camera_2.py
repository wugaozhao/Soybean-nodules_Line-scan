# -*- coding: utf-8 -*-

import sys
import os
import platform
import ctypes
from datetime import datetime
import traceback

import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QLineEdit,
                             QGroupBox, QFormLayout, QTextEdit, QFileDialog,
                             QInputDialog)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap

# SDK路径配置
MV_SDK_PATH = r"D:\MVS\MVS\Development\Samples\Python\MvImport"
if MV_SDK_PATH not in sys.path:
    sys.path.append(MV_SDK_PATH)

# 兼容不同操作系统加载动态库
currentsystem = platform.system()
if currentsystem == 'Windows':
    MVCAM_PATH = os.getenv('MVCAM_COMMON_RUNENV')
    if MVCAM_PATH and os.path.exists(os.path.join(MVCAM_PATH, "Samples", "Python", "MvImport")):
        sys.path.append(os.path.join(MVCAM_PATH, "Samples", "Python", "MvImport"))
else:
    sys.path.append(os.path.join("../..", "..", "MvImport"))

try:
    from MvCameraControl_class import *
except Exception as e:
    print(f"导入MvCameraControl_class失败: {e}")
    traceback.print_exc()
    sys.exit(1)


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


class CameraThread(QThread):
    """相机取流线程"""
    image_update = pyqtSignal(object)  # 更新预览图像信号
    frame_received = pyqtSignal(np.ndarray)  # 收到一帧图像信号
    log_signal = pyqtSignal(str)  # 日志信号
    finished_signal = pyqtSignal()  # 拍摄完成信号

    def __init__(self):
        try:
            super().__init__()
            self.cam = None
            self.is_grabbing = False
            self.is_running = False
            self.frames = []  # 存储所有帧
            self.image_height = 0
            self.image_width = 0
            self.total_height = 0  # 合成图像总高度
            self.nPayloadSize = 0
        except Exception as e:
            print(f"CameraThread初始化异常: {e}")
            traceback.print_exc()

    def set_camera_params(self, exposure_time=None, line_rate=None, digital_shift=None):
        """设置相机参数"""
        if self.cam is None:
            self.log_signal.emit("错误: 相机未初始化")
            return False
        try:
            if exposure_time is not None:
                try:
                    exp_value = float(exposure_time)
                    ret = self.cam.MV_CC_SetFloatValue("ExposureTime", exp_value)
                    if ret != 0:
                        self.log_signal.emit(f"设置曝光时间失败: 0x{ret:X}")
                    else:
                        self.log_signal.emit(f"曝光时间设置为: {exposure_time}us")
                except (ValueError, TypeError) as e:
                    self.log_signal.emit(f"曝光时间值错误: {e}")
                except Exception as e:
                    self.log_signal.emit(f"设置曝光时间异常: {str(e)}")

            if line_rate is not None:
                try:
                    line_rate_value = int(line_rate)
                    ret = self.cam.MV_CC_SetIntValue("LineFrequency", line_rate_value)
                    if ret != 0:
                        self.log_signal.emit(f"设置行频失败: 0x{ret:X}")
                    else:
                        self.log_signal.emit(f"行频设置为: {line_rate}")
                        # 启发行频使能
                        ret = self.cam.MV_CC_SetBoolValue("AcquisitionLineRateEnable", True)
                        if ret != 0:
                            self.log_signal.emit(f"启发行频使能失败: 0x{ret:X}")
                except (ValueError, TypeError) as e:
                    self.log_signal.emit(f"行频值错误: {e}")
                except Exception as e:
                    self.log_signal.emit(f"设置行频异常: {str(e)}")

            if digital_shift is not None:
                try:
                    ret = self.cam.MV_CC_SetBoolValue("DigitalShiftEnable", True)
                    if ret == 0:
                        ret = self.cam.MV_CC_SetFloatValue("DigitalShift", float(digital_shift))
                    if ret != 0:
                        self.log_signal.emit(f"设置数字增益失败: 0x{ret:X}")
                    else:
                        self.log_signal.emit(f"数字增益设置为: {digital_shift}")
                except (ValueError, TypeError) as e:
                    self.log_signal.emit(f"数字增益值错误: {e}")
                except Exception as e:
                    self.log_signal.emit(f"设置数字增益异常: {str(e)}")

            return True
        except Exception as e:
            self.log_signal.emit(f"设置参数异常: {str(e)}")
            traceback.print_exc()
            return False

    def init_camera(self, device_index=0):
        """初始化相机"""
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

            try:
                ret = MvCamera.MV_CC_EnumDevices(t_layer_type, deviceList)
                if ret != 0:
                    self.log_signal.emit(f"枚举设备失败: 0x{ret:X}")
                    return False
            except Exception as e:
                self.log_signal.emit(f"枚举设备异常: {str(e)}")
                return False

            if deviceList.nDeviceNum == 0:
                self.log_signal.emit("未找到任何设备!")
                return False

            self.log_signal.emit(f"找到 {deviceList.nDeviceNum} 个设备")

            # 显示所有设备信息
            try:
                for i in range(deviceList.nDeviceNum):
                    mvcc_dev_info = cast(deviceList.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
                    if mvcc_dev_info.nTLayerType == MV_GIGE_DEVICE:
                        strModeName = decoding_char(mvcc_dev_info.SpecialInfo.stGigEInfo.chModelName)
                        self.log_signal.emit(f"设备[{i}]: {strModeName}")
            except Exception as e:
                self.log_signal.emit(f"读取设备信息异常: {str(e)}")

            if device_index >= deviceList.nDeviceNum:
                self.log_signal.emit("设备索引超出范围")
                return False

            # 创建相机实例
            try:
                self.cam = MvCamera()
                stDeviceList = cast(deviceList.pDeviceInfo[device_index], POINTER(MV_CC_DEVICE_INFO)).contents
                ret = self.cam.MV_CC_CreateHandle(stDeviceList)
                if ret != 0:
                    self.log_signal.emit(f"创建句柄失败: 0x{ret:X}")
                    return False
            except Exception as e:
                self.log_signal.emit(f"创建相机句柄异常: {str(e)}")
                return False

            # 打开设备
            try:
                ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
                if ret != 0:
                    self.log_signal.emit(f"打开设备失败: 0x{ret:X}")
                    return False
            except Exception as e:
                self.log_signal.emit(f"打开设备异常: {str(e)}")
                return False

            # 获取图像大小信息
            try:
                stParam = MVCC_INTVALUE()
                ret = self.cam.MV_CC_GetIntValue("Width", stParam)
                if ret == 0:
                    self.image_width = stParam.nCurValue
                else:
                    self.log_signal.emit(f"获取图像宽度失败: 0x{ret:X}")

                memset(byref(stParam), 0, sizeof(MVCC_INTVALUE))
                ret = self.cam.MV_CC_GetIntValue("Height", stParam)
                if ret == 0:
                    self.image_height = stParam.nCurValue
                else:
                    self.log_signal.emit(f"获取图像高度失败: 0x{ret:X}")

                self.log_signal.emit(f"图像尺寸: {self.image_width} x {self.image_height}")
            except Exception as e:
                self.log_signal.emit(f"获取图像尺寸异常: {str(e)}")
                return False

            # 获取PayloadSize
            try:
                memset(byref(stParam), 0, sizeof(MVCC_INTVALUE))
                ret = self.cam.MV_CC_GetIntValue("PayloadSize", stParam)
                if ret != 0:
                    self.log_signal.emit(f"获取PayloadSize失败: 0x{ret:X}")
                    return False
                self.nPayloadSize = stParam.nCurValue
                self.log_signal.emit(f"PayloadSize: {self.nPayloadSize}")
            except Exception as e:
                self.log_signal.emit(f"获取PayloadSize异常: {str(e)}")
                return False

            self.log_signal.emit("相机初始化成功")
            return True

        except Exception as e:
            self.log_signal.emit(f"初始化相机异常: {str(e)}")
            traceback.print_exc()
            return False

    def start_grabbing(self):
        """开始取流"""
        try:
            if self.cam is None:
                self.log_signal.emit("相机未初始化")
                return False

            ret = self.cam.MV_CC_StartGrabbing()
            if ret != 0:
                self.log_signal.emit(f"开始取流失败: 0x{ret:X}")
                return False

            self.is_grabbing = True
            self.frames = []
            self.total_height = 0
            self.log_signal.emit("开始取流...")
            return True
        except Exception as e:
            self.log_signal.emit(f"开始取流异常: {str(e)}")
            traceback.print_exc()
            return False

    def stop_grabbing(self):
        """停止取流"""
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
        """线程主循环，连续获取图像"""
        try:
            self.is_running = True

            while self.is_running:
                if not self.is_grabbing or self.cam is None:
                    QThread.msleep(10)
                    continue

                try:
                    stOutFrame = MV_FRAME_OUT()
                    memset(byref(stOutFrame), 0, sizeof(stOutFrame))

                    ret = self.cam.MV_CC_GetImageBuffer(stOutFrame, 500)
                    if ret == 0 and stOutFrame.pBufAddr is not None:
                        try:
                            # 解码HB数据
                            dst_size = self.nPayloadSize
                            HB_decode_param = MV_CC_HB_DECODE_PARAM()
                            HB_decode_param.pSrcBuf = stOutFrame.pBufAddr
                            HB_decode_param.nSrcLen = stOutFrame.stFrameInfo.nFrameLen
                            HB_decode_param.nDstBufSize = dst_size
                            HB_decode_param.pDstBuf = (c_ubyte * dst_size)()
                            ret = self.cam.MV_CC_HBDecode(HB_decode_param)

                            if ret == 0:
                                # 将解码后的数据转换为numpy数组
                                width = HB_decode_param.nWidth
                                height = HB_decode_param.nHeight
                                pixel_type = HB_decode_param.enDstPixelType

                                # 根据像素格式计算每像素字节数
                                if pixel_type == PixelType_Gvsp_RGB8_Packed:
                                    bytes_per_pixel = 3
                                elif pixel_type == PixelType_Gvsp_Mono8:
                                    bytes_per_pixel = 1
                                else:
                                    bytes_per_pixel = 3

                                data = (c_ubyte * (width * height * bytes_per_pixel)).from_address(
                                    ctypes.addressof(HB_decode_param.pDstBuf.contents))
                                img_array = np.frombuffer(data, dtype=np.uint8)
                                img_array = img_array.reshape((height, width, bytes_per_pixel))

                                # 发送帧数据
                                self.frame_received.emit(img_array)

                                # 更新预览（显示最新一帧）
                                self.image_update.emit(img_array)
                        except Exception as e:
                            self.log_signal.emit(f"处理图像异常: {str(e)}")
                            traceback.print_exc()
                        finally:
                            try:
                                self.cam.MV_CC_FreeImageBuffer(stOutFrame)
                            except Exception as e:
                                self.log_signal.emit(f"释放图像缓存异常: {str(e)}")
                except Exception as e:
                    self.log_signal.emit(f"获取图像帧异常: {str(e)}")
                    traceback.print_exc()
                    QThread.msleep(100)  # 出错时等待100ms再继续

            self.is_grabbing = False
            self.finished_signal.emit()
            self.log_signal.emit("取流线程结束")
        except Exception as e:
            self.log_signal.emit(f"取流线程运行异常: {str(e)}")
            traceback.print_exc()
            self.is_grabbing = False

    def cleanup(self):
        """清理资源"""
        try:
            self.is_running = False
            self.stop_grabbing()

            if self.cam is not None:
                try:
                    self.cam.MV_CC_CloseDevice()
                except Exception as e:
                    self.log_signal.emit(f"关闭设备异常: {str(e)}")

                try:
                    self.cam.MV_CC_DestroyHandle()
                except Exception as e:
                    self.log_signal.emit(f"销毁句柄异常: {str(e)}")

                self.cam = None

            try:
                MvCamera.MV_CC_Finalize()
            except Exception as e:
                self.log_signal.emit(f"SDK反初始化异常: {str(e)}")

            self.log_signal.emit("相机资源已释放")
        except Exception as e:
            self.log_signal.emit(f"清理资源异常: {str(e)}")
            traceback.print_exc()


class ImageSynthesizer:
    """图像合成器，将多帧线扫描图像合成为完整图像"""

    def __init__(self):
        try:
            self.reset()
        except Exception as e:
            print(f"ImageSynthesizer初始化异常: {e}")
            traceback.print_exc()

    def reset(self):
        """重置合成器"""
        try:
            self.frames = []
            self.total_height = 0
            self.width = 0
            self.bytes_per_pixel = 1
            self.combined_image = None
        except Exception as e:
            print(f"重置合成器异常: {e}")
            traceback.print_exc()

    def add_frame(self, img_array):
        """添加一帧图像"""
        try:
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
                self.frames = []

            if width != self.width:
                return False

            self.frames.append(img_array)
            self.total_height += height
            return True
        except Exception as e:
            print(f"添加帧异常: {e}")
            traceback.print_exc()
            return False

    def get_combined_image(self):
        """获取合成后的完整图像"""
        try:
            if not self.frames:
                return None

            # 合成图像
            combined = np.vstack(self.frames)
            # 如果图像是单通道，压缩最后一维
            if combined.shape[-1] == 1:
                combined = combined.squeeze(axis=-1)
            return combined
        except Exception as e:
            print(f"合成图像异常: {e}")
            traceback.print_exc()
            return None

    def get_frame_count(self):
        """获取帧数"""
        try:
            return len(self.frames)
        except Exception as e:
            print(f"获取帧数异常: {e}")
            return 0

    def get_total_height(self):
        """获取总高度"""
        try:
            return self.total_height
        except Exception as e:
            print(f"获取总高度异常: {e}")
            return 0


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        try:
            super().__init__()
            self.camera_thread = None
            self.synthesizer = ImageSynthesizer()
            self.is_capturing = False
            self.current_file_name = ""
            self.init_ui()
        except Exception as e:
            print(f"主窗口初始化异常: {e}")
            traceback.print_exc()
            raise

    def init_ui(self):
        """初始化UI"""
        try:
            self.setWindowTitle("线扫描相机控制系统")
            self.setGeometry(100, 100, 1200, 800)

            # 中央widget
            central_widget = QWidget()
            self.setCentralWidget(central_widget)

            # 主布局
            main_layout = QHBoxLayout(central_widget)

            # ==================== 左侧控制面板 ====================
            left_panel = QWidget()
            left_panel.setFixedWidth(300)
            left_layout = QVBoxLayout(left_panel)

            # 相机参数组
            param_group = QGroupBox("相机参数")
            param_layout = QFormLayout()

            self.exposure_input = QLineEdit("2000")
            self.line_rate_input = QLineEdit("2000")
            self.digital_shift_input = QLineEdit("0")

            param_layout.addRow("曝光时间(us):", self.exposure_input)
            param_layout.addRow("行频(Hz):", self.line_rate_input)
            param_layout.addRow("数字增益:", self.digital_shift_input)

            self.apply_params_btn = QPushButton("应用参数")
            self.apply_params_btn.clicked.connect(self.apply_params)
            param_layout.addRow(self.apply_params_btn)

            param_group.setLayout(param_layout)
            left_layout.addWidget(param_group)

            # 控制按钮组
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

            # 设备信息显示
            info_group = QGroupBox("设备信息")
            info_layout = QVBoxLayout()
            self.info_label = QLabel("未初始化")
            self.info_label.setWordWrap(True)
            info_layout.addWidget(self.info_label)
            info_group.setLayout(info_layout)
            left_layout.addWidget(info_group)

            left_layout.addStretch()

            # ==================== 右侧图像预览区域 ====================
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

            # ==================== 底部日志区域 ====================
            log_group = QGroupBox("日志信息")
            log_layout = QVBoxLayout()
            self.log_text = QTextEdit()
            self.log_text.setReadOnly(True)
            self.log_text.setMaximumHeight(150)
            log_layout.addWidget(self.log_text)
            log_group.setLayout(log_layout)

            # 添加到主布局
            main_layout.addWidget(left_panel)
            right_layout.addWidget(log_group)
            main_layout.addWidget(right_panel, 1)
        except Exception as e:
            print(f"初始化UI异常: {e}")
            traceback.print_exc()
            raise

    def log(self, message):
        """添加日志"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.append(f"[{timestamp}] {message}")
            # 自动滚动到底部
            scrollbar = self.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        except Exception as e:
            print(f"添加日志异常: {e}")

    def init_camera(self):
        """初始化相机"""
        try:
            self.log("正在初始化相机...")

            self.camera_thread = CameraThread()
            self.camera_thread.log_signal.connect(self.log)

            # 连接信号
            self.camera_thread.image_update.connect(self.update_preview)
            self.camera_thread.frame_received.connect(self.on_frame_received)

            # 初始化相机
            if self.camera_thread.init_camera(device_index=0):
                self.start_btn.setEnabled(True)
                self.info_label.setText("相机已就绪")
                self.log("相机初始化成功")
            else:
                self.start_btn.setEnabled(False)
                self.info_label.setText("相机初始化失败")
                self.log("相机初始化失败")
                self.camera_thread = None

        except Exception as e:
            self.log(f"初始化失败: {str(e)}")
            traceback.print_exc()
            self.start_btn.setEnabled(False)

    def apply_params(self):
        """应用相机参数"""
        try:
            if self.camera_thread is None:
                self.log("请先初始化相机")
                return

            if self.is_capturing:
                self.log("拍摄中，请先停止拍摄再修改参数")
                return

            try:
                exposure = float(self.exposure_input.text())
                line_rate = int(self.line_rate_input.text())
                digital_shift = float(self.digital_shift_input.text())

                self.camera_thread.set_camera_params(
                    exposure_time=exposure,
                    line_rate=line_rate,
                    digital_shift=digital_shift
                )
                self.log("参数设置完成")
            except ValueError as e:
                self.log(f"参数格式错误: {str(e)}")
            except Exception as e:
                self.log(f"应用参数异常: {str(e)}")
                traceback.print_exc()
        except Exception as e:
            self.log(f"apply_params异常: {str(e)}")
            traceback.print_exc()

    def start_capture(self):
        """开始拍摄"""
        try:
            if self.camera_thread is None:
                self.log("请先初始化相机")
                return

            if self.is_capturing:
                self.log("已在拍摄中")
                return

            # 弹出文件名输入框
            file_name, ok = QInputDialog.getText(self, "保存文件名", "请输入文件名（不含扩展名）:")
            if not ok or not file_name.strip():
                self.log("未输入文件名，取消拍摄")
                return

            self.current_file_name = file_name.strip()

            # 重置合成器
            self.synthesizer = ImageSynthesizer()

            # 应用当前参数
            self.apply_params()



            # 开始取流
            if self.camera_thread.start_grabbing():
                print("开始拍摄？")
                self.is_capturing = True
                self.start_btn.setEnabled(False)
                self.stop_btn.setEnabled(True)
                self.init_cam_btn.setEnabled(False)
                # self.frame_buffer.clear()
                # self.cam.MV_CC_StartGrabbing()
                # self.is_grabbing = True
                # self.label_status.setText("状态：采集中...（白平衡自动运行）")
            #
            #     # 启动取流线程
            #     if not self.camera_thread.isRunning():
            #         self.camera_thread.start()
            #     self.camera_thread.image_update.connect(self.update_preview)
            #     self.camera_thread.frame_received.connect(self.on_frame_received)
            #     self.log(f"开始拍摄，文件名: {self.current_file_name}")
            # else:
            #     self.log("开始拍摄失败")
            #     self.is_capturing = False
            #     self.start_btn.setEnabled(True)
            #     self.stop_btn.setEnabled(False)
            #     self.init_cam_btn.setEnabled(True)
        except Exception as e:
            self.log(f"开始拍摄异常: {str(e)}")
            traceback.print_exc()
            self.is_capturing = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.init_cam_btn.setEnabled(True)

        # ==========================
        # 【彩色】官方取图 + 正确显示（已修复发蓝）
        # ==========================
        def loop_fetch(self):
            if not self.is_grabbing:
                return

            try:
                st_out_frame = MV_FRAME_OUT()
                memset(byref(st_out_frame), 0, sizeof(st_out_frame))
                ret = self.cam.MV_CC_GetImageBuffer(st_out_frame, 100)
                if ret != 0:
                    return

                w = st_out_frame.stFrameInfo.nWidth
                h = st_out_frame.stFrameInfo.nHeight
                data_ptr = st_out_frame.pBufAddr

                # 彩色图像转 numpy
                arr = np.ctypeslib.as_array(cast(data_ptr, POINTER(c_ubyte)), shape=(h * w * 3,))
                img = arr.reshape(h, w, 3)

                # ====================== 关键修复：删除错误的颜色转换（解决发蓝） ======================
                # 这行已经删掉了，你原来的代码就是这里导致发蓝

                self.frame_buffer.append(img)
                if len(self.frame_buffer) > self.MAX_HEIGHT:
                    self.frame_buffer.pop(0)

                if len(self.frame_buffer) > 10:
                    self.current_img = np.vstack(self.frame_buffer)
                    self.show_image(self.current_img)

                self.cam.MV_CC_FreeImageBuffer(st_out_frame)

            except Exception as e:
                pass

        # ==========================
        # 显示彩色图
        # ==========================

    def stop_capture(self):
        """停止拍摄并保存图像"""
        try:
            if not self.is_capturing:
                return

            self.log("正在停止拍摄...")

            # 停止取流
            if self.camera_thread is not None:
                self.camera_thread.stop_grabbing()

            self.is_capturing = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.init_cam_btn.setEnabled(True)

            # 保存合成图像
            self.save_combined_image()
        except Exception as e:
            self.log(f"停止拍摄异常: {str(e)}")
            traceback.print_exc()
            self.is_capturing = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.init_cam_btn.setEnabled(True)

    def on_frame_received(self, img_array):
        """收到一帧图像"""
        try:
            print("???",img_array)
            if self.is_capturing and img_array is not None:
                self.synthesizer.add_frame(img_array)
                frame_count = self.synthesizer.get_frame_count()
                if frame_count % 100 == 0:
                    self.log(f"已接收 {frame_count} 帧，合成高度: {self.synthesizer.get_total_height()} 像素")
        except Exception as e:
            self.log(f"接收帧异常: {str(e)}")
            traceback.print_exc()

    def update_preview(self, img_array):
        """更新预览图像"""
        try:
            if img_array is None:
                return

            # 转换为QPixmap显示
            if len(img_array.shape) == 3:
                if img_array.shape[2] == 3:
                    height, width, _ = img_array.shape
                    bytes_per_line = 3 * width
                    qimg = QImage(img_array.data, width, height, bytes_per_line, QImage.Format_RGB888)
                elif img_array.shape[2] == 1:
                    height, width, _ = img_array.shape
                    qimg = QImage(img_array.data, width, height, QImage.Format_Grayscale8)
                else:
                    return
            else:
                height, width = img_array.shape
                qimg = QImage(img_array.data, width, height, QImage.Format_Grayscale8)

            # 缩放以适应预览区域
            pixmap = QPixmap.fromImage(qimg)
            scaled_pixmap = pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.preview_label.setPixmap(scaled_pixmap)

        except Exception as e:
            self.log(f"预览更新异常: {str(e)}")
            traceback.print_exc()

    def save_combined_image(self):
        """保存合成后的完整图像"""
        try:
            combined_img = self.synthesizer.get_combined_image()

            if combined_img is None:
                self.log("没有接收到任何图像数据")
                return

            if combined_img.size == 0:
                self.log("合成图像为空")
                return

            try:
                # 创建保存目录
                save_dir = "D:/"
                date_folder = datetime.now().strftime("%Y%m%d")
                save_path = os.path.join(save_dir, date_folder)

                if not os.path.exists(save_path):
                    os.makedirs(save_path)

                # 保存图像
                from PIL import Image

                if len(combined_img.shape) == 2:
                    img = Image.fromarray(combined_img.astype(np.uint8), mode='L')
                elif len(combined_img.shape) == 3 and combined_img.shape[2] == 3:
                    img = Image.fromarray(combined_img.astype(np.uint8), mode='RGB')
                else:
                    img = Image.fromarray(combined_img.squeeze().astype(np.uint8), mode='L')

                full_path = os.path.join(save_path, f"{self.current_file_name}.bmp")
                img.save(full_path)

                frame_count = self.synthesizer.get_frame_count()
                total_height = self.synthesizer.get_total_height()

                self.log(f"图像已保存: {full_path}")
                self.log(f"合成信息: {frame_count} 帧, 图像尺寸 {combined_img.shape[1]} x {total_height}")
                self.info_label.setText(
                    f"已保存: {self.current_file_name}.bmp\n尺寸: {combined_img.shape[1]} x {total_height}")

            except ImportError:
                self.log("错误: 请安装PIL/Pillow库: pip install Pillow")
            except OSError as e:
                self.log(f"文件保存错误: {str(e)}")
            except Exception as e:
                self.log(f"保存图像失败: {str(e)}")
                traceback.print_exc()
        except Exception as e:
            self.log(f"保存图像异常: {str(e)}")
            traceback.print_exc()

    def closeEvent(self, event):
        """关闭窗口事件"""
        try:
            self.log("正在关闭程序...")
            if self.camera_thread is not None:
                self.camera_thread.cleanup()
            event.accept()
        except Exception as e:
            self.log(f"关闭程序异常: {str(e)}")
            traceback.print_exc()
            event.accept()  # 即使出错也允许关闭


def main():
    """主函数"""
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        print(f"程序运行异常: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()