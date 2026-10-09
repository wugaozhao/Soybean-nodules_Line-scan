import sys
import cv2
import numpy as np
import ctypes
from ctypes import *

#成功取图，但保存效果有问题，拍摄与最终存图不符

# ================== 改成你自己的MVS路径 ==================
MV_SDK_PATH = r"D:\MVS\MVS\Development\Samples\Python\MvImport"
sys.path.append(MV_SDK_PATH)

from MvCameraControl_class import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap


# ======================================================
# 彩色线阵相机调试工具（已修复：颜色发蓝 + 白平衡自动校准）
# ======================================================
class CameraDebugWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("彩色线阵相机调试工具")
        self.setFixedSize(1000, 750)

        # ========== 界面 ==========
        self.img_label = QLabel()
        self.img_label.setStyleSheet("background-color:#1a1a1a; border:1px solid #666;")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setFixedSize(960, 540)

        self.edit_exposure = QLineEdit("1000")
        self.edit_line_rate = QLineEdit("15000")
        self.btn_set_exposure = QPushButton("设置曝光")
        self.btn_set_line_rate = QPushButton("设置行频")
        self.btn_start = QPushButton("开始采集")
        self.btn_stop = QPushButton("停止采集")
        self.btn_save = QPushButton("保存图像")
        self.label_status = QLabel("状态：未启动")

        # ========== 布局 ==========
        layout = QVBoxLayout()
        layout.addWidget(self.img_label)

        h1 = QHBoxLayout()
        h1.addWidget(QLabel("曝光(us):"))
        h1.addWidget(self.edit_exposure)
        h1.addWidget(self.btn_set_exposure)
        h1.addWidget(QLabel("行频(Hz):"))
        h1.addWidget(self.edit_line_rate)
        h1.addWidget(self.btn_set_line_rate)
        layout.addLayout(h1)

        h2 = QHBoxLayout()
        h2.addWidget(self.btn_start)
        h2.addWidget(self.btn_stop)
        h2.addWidget(self.btn_save)
        layout.addLayout(h2)

        layout.addWidget(self.label_status)
        self.setLayout(layout)

        # ========== 相机变量 ==========
        self.cam = MvCamera()
        self.is_grabbing = False
        self.frame_buffer = []
        self.current_img = None
        self.MAX_HEIGHT = 800

        # 初始化
        self.init_camera()

        # 预览定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.loop_fetch)
        self.timer.start(30)

        # 绑定
        self.btn_set_exposure.clicked.connect(self.set_exposure)
        self.btn_set_line_rate.clicked.connect(self.set_line_rate)
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_save.clicked.connect(self.save_img)

    # ==========================
    # 初始化相机（彩色 + 白平衡已开启）
    # ==========================
    def init_camera(self):
        try:
            self.dev_list = MV_CC_DEVICE_INFO_LIST()
            MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, self.dev_list)

            if self.dev_list.nDeviceNum == 0:
                QMessageBox.warning(self, "错误", "未发现相机")
                return

            dev_info = cast(self.dev_list.pDeviceInfo[0], POINTER(MV_CC_DEVICE_INFO)).contents
            self.cam.MV_CC_CreateHandle(dev_info)
            self.cam.MV_CC_OpenDevice()

            # 彩色线阵 关键设置
            self.cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
            self.cam.MV_CC_SetEnumValue("PixelFormat", 0x02180014)  # RGB8 彩色

            # ====================== 【关键】开启自动白平衡 ======================
            # 0=关闭 1=单次 2=连续自动
            self.cam.MV_CC_SetEnumValue("BalanceWhiteAuto", 2)
            # ====================== 修复偏色必备 ======================

            self.set_exposure()
            self.set_line_rate()
            self.label_status.setText("状态：相机初始化成功（彩色 + 自动白平衡已开启）")

        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def set_exposure(self):
        try:
            exp = float(self.edit_exposure.text())
            self.cam.MV_CC_SetFloatValue("ExposureTime", exp)
            self.label_status.setText(f"曝光：{exp}us")
        except:
            QMessageBox.warning(self, "错误", "曝光失败")

    def set_line_rate(self):
        try:
            rate = float(self.edit_line_rate.text())
            self.cam.MV_CC_SetFloatValue("AcquisitionLineRate", rate)
            self.label_status.setText(f"行频：{rate}Hz")
        except:
            QMessageBox.warning(self, "错误", "行频失败")

    def start(self):
        self.frame_buffer.clear()
        self.cam.MV_CC_StartGrabbing()
        self.is_grabbing = True
        self.label_status.setText("状态：采集中...（白平衡自动运行）")

    def stop(self):
        self.is_grabbing = False
        self.cam.MV_CC_StopGrabbing()
        self.label_status.setText("状态：已停止")

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
    def show_image(self, img):
        h, w, ch = img.shape
        q_img = QImage(img.data, w, h, 3 * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(q_img).scaled(self.img_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.img_label.setPixmap(pix)

    def save_img(self):
        if self.current_img is None:
            self.label_status.setText("无图像")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存", "", "*.jpg")
        if path:
            save = cv2.cvtColor(self.current_img, cv2.COLOR_RGB2BGR)
            cv2.imwrite(path, save)
            self.label_status.setText("已保存：" + path)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = CameraDebugWindow()
    win.show()
    sys.exit(app.exec_())