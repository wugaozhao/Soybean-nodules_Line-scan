# -*- coding: utf-8 -*-

import sys
import os
import platform
import ctypes
import time
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
            self.image_height = 0
            self.image_width = 0
            self.nPayloadSize = 0
        except Exception as e:
            print(f"CameraThread初始化异常: {e}")
            traceback.print_exc()

    def _node_can_write(self, node_name):
        """检查GenICam节点是否可写，节点不存在时返回False。"""
        try:
            access_mode = MV_XML_AccessMode()
            ret = self.cam.MV_XML_GetNodeAccessMode(node_name, access_mode)
            if ret != 0:
                return False
            value = access_mode.value if hasattr(access_mode, "value") else int(access_mode)
            return value in (AM_WO, AM_RW)
        except Exception:
            return False

    def _set_enum_by_string_or_value(self, node_name, enum_name, enum_value):
        try:
            ret = self.cam.MV_CC_SetEnumValueByString(node_name, enum_name)
            if ret == 0:
                return 0
        except Exception:
            pass
        return self.cam.MV_CC_SetEnumValue(node_name, enum_value)

    def load_feature_file(self, feature_file):
        """Load an MVS FeatureSave file exported from the camera client."""
        if self.cam is None:
            self.log_signal.emit("错误: 相机未初始化")
            return False
        if not feature_file:
            return True
        try:
            ret = self.cam.MV_CC_FeatureLoad(feature_file)
            if ret == 0:
                self.log_signal.emit(f"MVS特性文件加载成功: {feature_file}")
                return True
            self.log_signal.emit(f"MVS特性文件加载失败: 0x{ret:X}, {feature_file}")
            return False
        except Exception as e:
            self.log_signal.emit(f"加载MVS特性文件异常: {str(e)}")
            traceback.print_exc()
            return False

    def _set_numeric_node(self, node_name, value):
        """Try the numeric setter variants used by MVS GenICam nodes."""
        attempts = []

        try:
            ret = self.cam.MV_CC_SetIntValueEx(node_name, int(value))
            if ret == 0:
                return True, "Int64"
            attempts.append(f"Int64=0x{ret:X}")
        except Exception as exc:
            attempts.append(f"Int64={exc}")

        try:
            ret = self.cam.MV_CC_SetIntValue(node_name, int(value))
            if ret == 0:
                return True, "Int"
            attempts.append(f"Int=0x{ret:X}")
        except Exception as exc:
            attempts.append(f"Int={exc}")

        try:
            ret = self.cam.MV_CC_SetFloatValue(node_name, float(value))
            if ret == 0:
                return True, "Float"
            attempts.append(f"Float=0x{ret:X}")
        except Exception as exc:
            attempts.append(f"Float={exc}")

        return False, ", ".join(attempts)

    def _set_rgb_direct_node(self, label, value, node_names):
        failures = []
        for node_name in node_names:
            writable = self._node_can_write(node_name)
            success, detail = self._set_numeric_node(node_name, value)
            if success:
                self.log_signal.emit(f"{label} 曝光/亮度设置成功: {value} ({node_name}, {detail})")
                return True
            failures.append(f"{node_name}[writable={writable}]: {detail}")
        self.log_signal.emit(f"{label} 直接节点写入失败: {'; '.join(failures)}")
        return False

    def _set_rgb_by_selector(self, label, value, selector_names, value_names, enum_names):
        failures = []
        for selector_name in selector_names:
            for enum_name in enum_names:
                try:
                    selector_ret = self.cam.MV_CC_SetEnumValueByString(selector_name, enum_name)
                except Exception as exc:
                    failures.append(f"{selector_name}={enum_name}: {exc}")
                    continue

                if selector_ret != 0:
                    failures.append(f"{selector_name}={enum_name}: 0x{selector_ret:X}")
                    continue

                for value_name in value_names:
                    success, detail = self._set_numeric_node(value_name, value)
                    if success:
                        self.log_signal.emit(
                            f"{label} 曝光/亮度设置成功: {value} "
                            f"({selector_name}={enum_name}, {value_name}, {detail})"
                        )
                        return True
                    failures.append(f"{selector_name}={enum_name}, {value_name}: {detail}")
        self.log_signal.emit(f"{label} 选择器节点写入失败: {'; '.join(failures[:12])}")
        return False

    def set_rgb_exposure(self, red=900, green=900, blue=900, nodes=None):
        """Set LC330 RGB LED exposure/brightness nodes shown in MVS Exposure Control."""
        if self.cam is None:
            self.log_signal.emit("错误: 相机未初始化")
            return False
        try:
            configured_nodes = nodes or {}
            values = {
                "Red": ("red", int(red), ("Red", "R")),
                "Green": ("green", int(green), ("Green", "G")),
                "Blue": ("blue", int(blue), ("Blue", "B")),
            }

            ok = True
            selector_names = (
                "ExposureSelector",
                "ExposureChannel",
                "ExposureControlSelector",
                "LightSelector",
                "LightSourceSelector",
                "LightChannelSelector",
                "ColorSelector",
            )
            value_names = (
                "ExposureTime",
                "ExposureValue",
                "Exposure",
                "LightValue",
                "LightIntensity",
                "LightBrightness",
                "StrobeDuration",
                "StrobeLineDuration",
            )

            for label, (key, value, enum_names) in values.items():
                value = max(0, min(1023, value))

                direct_nodes = configured_nodes.get(key) if isinstance(configured_nodes, dict) else None
                if isinstance(direct_nodes, str):
                    direct_nodes = (direct_nodes,)
                if not direct_nodes:
                    direct_nodes = (
                        label,
                        f"{label}Exposure",
                        f"{label}ExposureTime",
                        f"{label}Light",
                        f"{label}LightValue",
                        f"{label}LightIntensity",
                        f"Light{label}",
                        f"Light{label}Value",
                        f"Exposure{label}",
                        f"ExposureTime{label}",
                    )

                if self._set_rgb_direct_node(label, value, direct_nodes):
                    continue

                if self._set_rgb_by_selector(label, value, selector_names, value_names, enum_names):
                    continue

                ok = False
                if label == "Red":
                    self.log_signal.emit(
                        "RGB节点仍未匹配。请在 MVS 中使用“保存特性/Feature Save”导出配置，"
                        "或把导出的配置文件发给我，用来确认真实节点名。"
                    )
                else:
                    ok = False
            return ok
        except Exception as e:
            self.log_signal.emit(f"设置RGB曝光/亮度异常: {str(e)}")
            traceback.print_exc()
            return False

    def set_line_scan_params(self, line_frequency=2000):
        """设置线扫相机内部行频参数。"""
        if self.cam is None:
            self.log_signal.emit("错误: 相机未初始化")
            return False
        try:
            line_frequency = int(line_frequency)

            # MVS线扫示例使用 AcquisitionLineRate；旧代码的 LineFrequency
            # 在部分LC系列相机上没有这个节点。
            rate_set = False
            failed_rates = []
            for node_name in ("AcquisitionLineRate", "LineFrequency"):
                ret = self.cam.MV_CC_SetIntValue(node_name, line_frequency)
                if ret == 0:
                    self.log_signal.emit(f"行频设置成功: {line_frequency} Hz ({node_name})")
                    rate_set = True
                    break
                failed_rates.append(f"{node_name}=0x{ret:X}")

            if not rate_set:
                self.log_signal.emit(f"设置行频失败: {', '.join(failed_rates)}")
                return False

            # 启用内部行频；不支持该节点的设备会保持当前相机配置。
            if self._node_can_write("AcquisitionLineRateEnable"):
                ret = self.cam.MV_CC_SetBoolValue("AcquisitionLineRateEnable", True)
                if ret == 0:
                    self.log_signal.emit("内部行频使能已开启")
                else:
                    self.log_signal.emit(f"内部行频使能设置失败: 0x{ret:X}")

            # 连续内部行频采集时关闭外部触发，避免LineStart/FrameBurst节点不匹配。
            self.set_trigger_mode()

            if self._node_can_write("Correct"):
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
        """设置为连续采集触发模式。"""
        if self.cam is None:
            self.log_signal.emit("错误: 相机未初始化")
            return False
        try:
            if not self._node_can_write("TriggerMode"):
                self.log_signal.emit("触发模式节点不可写，沿用相机当前配置")
                return True

            ret = self._set_enum_by_string_or_value("TriggerMode", "Off", MV_TRIGGER_MODE_OFF)
            if ret == 0:
                self.log_signal.emit("触发模式设置为: 连续采集")
            else:
                self.log_signal.emit(f"触发模式节点不兼容，沿用相机当前配置: 0x{ret:X}")
                return True

            return True
        except Exception as e:
            self.log_signal.emit(f"设置触发模式异常: {str(e)}")
            traceback.print_exc()
            return False

    def set_acquisition_mode_continuous(self):
        """部分线扫相机没有AcquisitionMode节点，设置失败时不影响取流。"""
        try:
            ret = self._set_enum_by_string_or_value("AcquisitionMode", "Continuous", MV_ACQ_MODE_CONTINUOUS)
            if ret == 0:
                self.log_signal.emit("采集模式设置为: 连续")
                return True
            self.log_signal.emit(f"采集模式节点不可写，沿用相机当前设置: 0x{ret:X}")
            return False
        except Exception as e:
            self.log_signal.emit(f"设置采集模式异常: {str(e)}")
            return False

    def set_color_pixel_format(self):
        """优先让相机输出彩色格式；节点不兼容时仍可在取流时转换/识别。"""
        if self.cam is None:
            return False

        pixel_formats = (
            ("RGB8", "RGB8_Packed"),
            ("RGB8Packed", "RGB8_Packed"),
            ("BGR8", "BGR8_Packed"),
            ("BGR8Packed", "BGR8_Packed"),
            ("BayerRG8", "BayerRG8"),
            ("BayerGR8", "BayerGR8"),
            ("BayerGB8", "BayerGB8"),
            ("BayerBG8", "BayerBG8"),
        )
        for enum_name, display_name in pixel_formats:
            try:
                ret = self.cam.MV_CC_SetEnumValueByString("PixelFormat", enum_name)
                if ret == 0:
                    self.log_signal.emit(f"像素格式设置为彩色: {display_name}")
                    return True
            except Exception:
                continue

        self.log_signal.emit("像素格式节点不可写或不兼容，沿用相机当前彩色配置")
        return False

    def _convert_to_rgb8(self, stOutFrame):
        width = stOutFrame.stFrameInfo.nWidth
        height = stOutFrame.stFrameInfo.nHeight
        n_rgb_size = width * height * 3

        stConvertParam = MV_CC_PIXEL_CONVERT_PARAM_EX()
        memset(byref(stConvertParam), 0, sizeof(stConvertParam))
        stConvertParam.nWidth = width
        stConvertParam.nHeight = height
        stConvertParam.pSrcData = stOutFrame.pBufAddr
        stConvertParam.nSrcDataLen = stOutFrame.stFrameInfo.nFrameLen
        stConvertParam.enSrcPixelType = stOutFrame.stFrameInfo.enPixelType
        stConvertParam.enDstPixelType = PixelType_Gvsp_RGB8_Packed
        stConvertParam.pDstBuffer = (c_ubyte * n_rgb_size)()
        stConvertParam.nDstBufferSize = n_rgb_size

        ret = self.cam.MV_CC_ConvertPixelTypeEx(stConvertParam)
        if ret != 0:
            return None, ret

        img_array = np.frombuffer(stConvertParam.pDstBuffer, dtype=np.uint8, count=n_rgb_size).copy()
        return img_array.reshape((height, width, 3)), 0

    def _frame_to_numpy(self, stOutFrame, frame_count):
        width = stOutFrame.stFrameInfo.nWidth
        height = stOutFrame.stFrameInfo.nHeight
        pixel_type = stOutFrame.stFrameInfo.enPixelType
        frame_len = stOutFrame.stFrameInfo.nFrameLen

        rgb8_types = (PixelType_Gvsp_RGB8_Packed,)
        bgr8_types = (PixelType_Gvsp_BGR8_Packed,)
        rgba8_types = (PixelType_Gvsp_RGBA8_Packed,)
        bgra8_types = (PixelType_Gvsp_BGRA8_Packed,)
        mono8_types = (PixelType_Gvsp_Mono8,)
        bayer_types = (
            PixelType_Gvsp_BayerGR8, PixelType_Gvsp_BayerRG8,
            PixelType_Gvsp_BayerGB8, PixelType_Gvsp_BayerBG8,
            PixelType_Gvsp_BayerRBGG8,
            PixelType_Gvsp_BayerGR10, PixelType_Gvsp_BayerRG10,
            PixelType_Gvsp_BayerGB10, PixelType_Gvsp_BayerBG10,
            PixelType_Gvsp_BayerGR12, PixelType_Gvsp_BayerRG12,
            PixelType_Gvsp_BayerGB12, PixelType_Gvsp_BayerBG12,
            PixelType_Gvsp_BayerGR10_Packed, PixelType_Gvsp_BayerRG10_Packed,
            PixelType_Gvsp_BayerGB10_Packed, PixelType_Gvsp_BayerBG10_Packed,
            PixelType_Gvsp_BayerGR12_Packed, PixelType_Gvsp_BayerRG12_Packed,
            PixelType_Gvsp_BayerGB12_Packed, PixelType_Gvsp_BayerBG12_Packed,
            PixelType_Gvsp_BayerGR16, PixelType_Gvsp_BayerRG16,
            PixelType_Gvsp_BayerGB16, PixelType_Gvsp_BayerBG16,
        )

        if pixel_type in rgb8_types:
            data = (c_ubyte * frame_len).from_address(ctypes.addressof(stOutFrame.pBufAddr.contents))
            img_array = np.frombuffer(data, dtype=np.uint8, count=width * height * 3).copy()
            if frame_count == 1:
                self.log_signal.emit(f"当前像素格式: RGB8 彩色 (0x{pixel_type:X})")
            return img_array.reshape((height, width, 3))

        if pixel_type in bgr8_types:
            data = (c_ubyte * frame_len).from_address(ctypes.addressof(stOutFrame.pBufAddr.contents))
            img_array = np.frombuffer(data, dtype=np.uint8, count=width * height * 3).copy()
            img_array = img_array.reshape((height, width, 3))[:, :, ::-1].copy()
            if frame_count == 1:
                self.log_signal.emit(f"当前像素格式: BGR8 彩色，已转RGB (0x{pixel_type:X})")
            return img_array

        if pixel_type in rgba8_types:
            data = (c_ubyte * frame_len).from_address(ctypes.addressof(stOutFrame.pBufAddr.contents))
            img_array = np.frombuffer(data, dtype=np.uint8, count=width * height * 4).copy()
            if frame_count == 1:
                self.log_signal.emit(f"当前像素格式: RGBA8 彩色，已去除Alpha (0x{pixel_type:X})")
            return img_array.reshape((height, width, 4))[:, :, :3].copy()

        if pixel_type in bgra8_types:
            data = (c_ubyte * frame_len).from_address(ctypes.addressof(stOutFrame.pBufAddr.contents))
            img_array = np.frombuffer(data, dtype=np.uint8, count=width * height * 4).copy()
            img_array = img_array.reshape((height, width, 4))[:, :, :3][:, :, ::-1].copy()
            if frame_count == 1:
                self.log_signal.emit(f"当前像素格式: BGRA8 彩色，已转RGB (0x{pixel_type:X})")
            return img_array

        if pixel_type in bayer_types:
            img_array, ret = self._convert_to_rgb8(stOutFrame)
            if img_array is not None:
                if frame_count == 1:
                    self.log_signal.emit(f"当前像素格式: Bayer 彩色，已转RGB (0x{pixel_type:X})")
                return img_array
            if frame_count == 1:
                self.log_signal.emit(f"Bayer转RGB失败: 0x{ret:X}")

        if pixel_type in mono8_types:
            data = (c_ubyte * frame_len).from_address(ctypes.addressof(stOutFrame.pBufAddr.contents))
            img_array = np.frombuffer(data, dtype=np.uint8, count=width * height).copy()
            if frame_count == 1:
                self.log_signal.emit(f"当前像素格式: Mono8 灰度 (0x{pixel_type:X})")
            return img_array.reshape((height, width, 1))

        if frame_len >= width * height * 3:
            data = (c_ubyte * frame_len).from_address(ctypes.addressof(stOutFrame.pBufAddr.contents))
            img_array = np.frombuffer(data, dtype=np.uint8, count=width * height * 3).copy()
            if frame_count == 1:
                self.log_signal.emit(f"未知像素格式 0x{pixel_type:X}，按RGB三通道处理")
            return img_array.reshape((height, width, 3))

        if frame_count == 1:
            self.log_signal.emit(f"不支持的像素格式: 0x{pixel_type:X}")
        return None

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
                try:
                    ret_timeout = MvCamera.MV_GIGE_SetEnumDevTimeout(200)
                    if ret_timeout == 0:
                        self.log_signal.emit("GigE设备枚举超时已设置为200ms")
                    else:
                        self.log_signal.emit(f"设置GigE设备枚举超时失败: 0x{ret_timeout:X}")
                except Exception as e:
                    self.log_signal.emit(f"设置GigE设备枚举超时异常: {str(e)}")

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
                        strSerialNumber = decoding_char(mvcc_dev_info.SpecialInfo.stGigEInfo.chSerialNumber)
                        self.log_signal.emit(f"设备[{i}]: {strModeName} (SN: {strSerialNumber})")
                    elif mvcc_dev_info.nTLayerType == MV_USB_DEVICE:
                        strModeName = decoding_char(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chModelName)
                        strSerialNumber = decoding_char(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber)
                        self.log_signal.emit(f"设备[{i}]: {strModeName} (SN: {strSerialNumber})")
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

            self.set_color_pixel_format()

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
                self.log_signal.emit("检测到: 线扫相机")

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

            # 设置触发模式
            self.set_trigger_mode()

            # 设置采集模式为连续
            self.set_acquisition_mode_continuous()

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

            # 先停止可能正在进行的采集
            self.stop_grabbing()

            # 启动取流线程（如果还没启动）
            if not self.isRunning():
                self.start()
                self.log_signal.emit("取流线程已启动")

            # 清空缓存
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
        """停止取流"""
        try:
            was_grabbing = self.is_grabbing
            self.is_grabbing = False
            if self.cam is not None and was_grabbing:
                ret = self.cam.MV_CC_StopGrabbing()
                if ret != 0:
                    self.log_signal.emit(f"停止取流失败: 0x{ret:X}")
                else:
                    self.log_signal.emit("停止取流")
                try:
                    self.cam.MV_CC_ClearImageBuffer()
                except Exception:
                    pass
        except Exception as e:
            self.log_signal.emit(f"停止取流异常: {str(e)}")
            traceback.print_exc()
            self.is_grabbing = False

    def run(self):
        """线程主循环，连续获取图像"""
        try:
            self.is_running = True
            frame_count = 0

            while self.is_running:
                if not self.is_grabbing or self.cam is None:
                    QThread.msleep(10)
                    continue

                try:
                    stOutFrame = MV_FRAME_OUT()
                    memset(byref(stOutFrame), 0, sizeof(stOutFrame))

                    ret = self.cam.MV_CC_GetImageBuffer(stOutFrame, 500)  # 超时0.5秒
                    if ret == 0 and stOutFrame.pBufAddr is not None:
                        frame_count += 1
                        try:
                            img_array = self._frame_to_numpy(stOutFrame, frame_count)
                            if img_array is None:
                                continue

                            # 发送帧数据
                            self.frame_received.emit(img_array)

                            # 更新预览（显示最新一帧）
                            self.image_update.emit(img_array)

                            # 每100帧输出一次调试信息
                            if frame_count % 100 == 0:
                                self.log_signal.emit(f"已获取 {frame_count} 帧图像")

                        except Exception as e:
                            self.log_signal.emit(f"处理图像异常: {str(e)}")
                            traceback.print_exc()
                        finally:
                            try:
                                self.cam.MV_CC_FreeImageBuffer(stOutFrame)
                            except Exception as e:
                                self.log_signal.emit(f"释放图像缓存异常: {str(e)}")
                    else:
                        # 获取图像超时或失败
                        if (not self.is_grabbing) and ret in (0x80000003, 0x80000007):
                            continue
                        if ret not in (0x80000007, 0x80000107):  # 无数据/GenICam超时不刷屏
                            self.log_signal.emit(f"获取图像失败: 0x{ret:X}")

                except Exception as e:
                    self.log_signal.emit(f"获取图像帧异常: {str(e)}")
                    traceback.print_exc()
                    QThread.msleep(100)  # 出错时等待100ms再继续

            self.is_grabbing = False
            self.finished_signal.emit()
            self.log_signal.emit(f"取流线程结束，共获取 {frame_count} 帧")
        except Exception as e:
            self.log_signal.emit(f"取流线程运行异常: {str(e)}")
            traceback.print_exc()
            self.is_grabbing = False

    def cleanup(self):
        """清理资源"""
        try:
            self.is_running = False
            self.stop_grabbing()

            # 等待线程结束
            if self.isRunning():
                self.wait(3000)  # 最多等待3秒

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
            self.capture_start_time = None
            self.target_line_frequency = 2000
            # 默认保存路径：桌面的CameraImages文件夹
            self.save_dir = os.path.join(os.path.expanduser("~"), "Desktop", "CameraImages")
            if not os.path.exists(self.save_dir):
                os.makedirs(self.save_dir)
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

            self.line_frequency_input = QLineEdit("2000")
            param_layout.addRow("行频(Hz):", self.line_frequency_input)

            self.apply_params_btn = QPushButton("应用参数")
            self.apply_params_btn.clicked.connect(self.apply_params)
            param_layout.addRow(self.apply_params_btn)

            param_group.setLayout(param_layout)
            left_layout.addWidget(param_group)

            # 保存设置组
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

    def select_save_path(self):
        """选择保存路径"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择保存路径", self.save_dir)
        if dir_path:
            self.save_dir = dir_path
            self.save_path_label.setText(f"当前路径:\n{self.save_dir}")
            self.log(f"保存路径已更改为: {self.save_dir}")

    def init_camera(self):
        """初始化相机"""
        try:
            self.log("正在初始化相机...")

            # 先清理之前的相机实例
            if self.camera_thread is not None:
                self.camera_thread.cleanup()
                self.camera_thread = None

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
                line_frequency = int(self.line_frequency_input.text())
                self.target_line_frequency = line_frequency
                if self.camera_thread.set_line_scan_params(line_frequency=line_frequency):
                    self.log("所有参数设置完成")
                else:
                    self.log("部分参数设置失败")
            except ValueError as e:
                self.log(f"行频值错误: 请输入整数")
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
                self.is_capturing = True
                self.capture_start_time = time.monotonic()
                self.start_btn.setEnabled(False)
                self.stop_btn.setEnabled(True)
                self.init_cam_btn.setEnabled(False)
                self.log(f"开始拍摄，文件名: {self.current_file_name}")
                speed_1200dpi = self.target_line_frequency / 1200 * 25.4
                self.log(f"目标行频: {self.target_line_frequency} line/s；1200dpi对应运动速度约 {speed_1200dpi:.1f} mm/s")
            else:
                self.log("开始拍摄失败")
                self.is_capturing = False
                self.start_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
                self.init_cam_btn.setEnabled(True)
        except Exception as e:
            self.log(f"开始拍摄异常: {str(e)}")
            traceback.print_exc()
            self.is_capturing = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.init_cam_btn.setEnabled(True)

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
            if self.is_capturing and img_array is not None:
                self.synthesizer.add_frame(img_array)
                frame_count = self.synthesizer.get_frame_count()
                if frame_count % 100 == 0:
                    total_lines = self.synthesizer.get_total_height()
                    elapsed = 0
                    if self.capture_start_time is not None:
                        elapsed = max(time.monotonic() - self.capture_start_time, 0.001)
                    actual_line_rate = total_lines / elapsed if elapsed else 0
                    self.log(
                        f"已接收 {frame_count} 帧 = {total_lines} 行，估算行频: {actual_line_rate:.0f} line/s"
                    )
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
                date_folder = datetime.now().strftime("%Y%m%d")
                save_path = os.path.join(self.save_dir, date_folder)

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
                elapsed = 0
                if self.capture_start_time is not None:
                    elapsed = max(time.monotonic() - self.capture_start_time, 0.001)
                actual_line_rate = total_height / elapsed if elapsed else 0

                self.log(f"图像已保存: {full_path}")
                self.log(
                    f"合成信息: {frame_count} 帧 = {total_height} 行, "
                    f"图像尺寸 {combined_img.shape[1]} x {total_height}, "
                    f"估算行频 {actual_line_rate:.0f} line/s"
                )
                self.info_label.setText(
                    f"已保存: {self.current_file_name}.bmp\n"
                    f"尺寸: {combined_img.shape[1]} x {total_height}\n"
                    f"估算行频: {actual_line_rate:.0f} line/s")

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
