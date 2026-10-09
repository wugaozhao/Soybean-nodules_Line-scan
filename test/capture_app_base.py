#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# conda install -c conda-forge pyqt opencv   #安装依赖
# pip install pypylon‑4.2.0‑cp39‑cp39‑win_amd64.whl   # 已下载的本地 whl
"""
Basler 可预览已采集的图像
"""
import os, sys
from datetime import datetime
from pathlib import Path

import cv2
cv2.setNumThreads(0)  # 禁止 OpenCV 内部多线程

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit,
    QHBoxLayout, QVBoxLayout, QFileDialog, QMessageBox, QGroupBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap, QPainter, QFont

try:
    from pypylon import pylon
except ImportError:
    sys.exit("pypylon 未安装，请 pip/conda 安装后再运行")


# ---------- Basler 相机 ----------
class BaslerCamera:
    def __init__(self):
        self.cam = None
        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = pylon.PixelType_BGR8packed

    def open(self, idx=0):
        tl = pylon.TlFactory.GetInstance()
        dev = tl.EnumerateDevices()
        if not dev:
            return False
        self.cam = pylon.InstantCamera(tl.CreateDevice(dev[idx]))
        self.cam.Open()
        self.cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
        return self.cam.IsGrabbing()

    def close(self):
        if self.cam:
            self.cam.StopGrabbing()
            self.cam.Close()
            self.cam = None

    def grab(self):
        if self.cam and self.cam.IsGrabbing():
            grab = self.cam.RetrieveResult(1000, pylon.TimeoutHandling_Return)
            if grab.GrabSucceeded():
                img = self.converter.Convert(grab)
                frame = img.GetArray()
                grab.Release()
                return frame
        return None


# ---------- 预览区（带红框文件名） ----------
class PreviewPane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._scale = 1.0
        self.setMinimumSize(640, 480)
        self.setStyleSheet("background:white;border:1px solid gray;")

        # 红框文件名
        self._fname = QLabel("", self)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(14)
        self._fname.setFont(font)
        self._fname.setAlignment(Qt.AlignCenter)
        self._fname.setStyleSheet("color:white;background:transparent;")
        self._fname.setFixedHeight(22)
        self._fname.raise_()                      # 置顶
        self._fname.setAttribute(Qt.WA_TransparentForMouseEvents)

    def setPixmap(self, pm: QPixmap, name: str = ""):
        self._pixmap = pm
        self._fname.setText(name)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        # 先刷黑底，保证文字区域透明
        painter.fillRect(self.rect(), Qt.white)
        if not self._pixmap:
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        pm_size = self._pixmap.size()
        widget_size = self.size()
        usable_h = widget_size.height() - self._fname.height()
        scale_w = widget_size.width() / pm_size.width()
        scale_h = usable_h / pm_size.height()
        scale = min(scale_w, scale_h) * self._scale
        new_w = int(pm_size.width() * scale)
        new_h = int(pm_size.height() * scale)
        x = (widget_size.width() - new_w) // 2
        y = self._fname.height() + (usable_h - new_h) // 2
        painter.drawPixmap(x, y, new_w, new_h, self._pixmap)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        self._scale = min(3.0, max(0.2, self._scale + (0.1 if delta > 0 else -0.1)))
        self.update()


# ---------- 主窗口 ----------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Basler 根系拍摄")
        self.resize(900, 700)

        self.cam = BaslerCamera()
        self.save_dir = Path.home() / "Pictures" / f"DATE-{datetime.now():%m%d}"
        self.init_ui()
        self.open_cam()

    def init_ui(self):
        # 上方功能区
        top = QHBoxLayout()
        grp_save = QGroupBox("文件存储")
        lay_save = QHBoxLayout()
        self.edt_savepath = QLineEdit(str(self.save_dir))
        self.btn_browse = QPushButton("浏览...")
        lay_save.addWidget(self.edt_savepath, 1)
        lay_save.addWidget(self.btn_browse)
        grp_save.setLayout(lay_save)
        top.addWidget(grp_save)

        grp_shot = QGroupBox("拍摄控制")
        lay_shot = QHBoxLayout()
        self.edt_no = QLineEdit()
        self.edt_no.setPlaceholderText("输入编号")
        self.btn_ok = QPushButton("OK")
        lay_shot.addWidget(QLabel("编号:"))
        lay_shot.addWidget(self.edt_no, 1)
        lay_shot.addWidget(self.btn_ok)
        grp_shot.setLayout(lay_shot)
        top.addWidget(grp_shot)
        top.addStretch()

        # 下方预览
        self.preview = PreviewPane()

        main = QVBoxLayout(self)
        main.addLayout(top)
        main.addWidget(self.preview, 1)

        # 信号
        self.btn_browse.clicked.connect(self.choose_save_dir)
        self.btn_ok.clicked.connect(self.shoot)
        self.edt_no.returnPressed.connect(self.shoot)

    def open_cam(self):
        if not self.cam.open(0):
            QMessageBox.critical(self, "错误", "未检测到 Basler 相机！")

    def choose_save_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择存储文件夹", str(self.save_dir))
        if d:
            self.save_dir = Path(d)
            self.edt_savepath.setText(str(self.save_dir))

    def shoot(self):
        no = self.edt_no.text().strip()
        if not no:
            QMessageBox.warning(self, "提示", "请输入编号！")
            return
        frame = self.cam.grab()
        if frame is None:
            QMessageBox.warning(self, "提示", "未获取到图像！")
            return
        self.save_dir.mkdir(parents=True, exist_ok=True)
        fname = self.save_dir / f"{no}.jpg"
        cv2.imwrite(str(fname), frame)

        # 关键：显示“已保存文件”+ 红框文件名
        pix = QPixmap(str(fname))
        self.preview.setPixmap(pix, fname.name)
        QMessageBox.information(self, "完成", f"已保存：{fname}")

    def closeEvent(self, a0):
        self.cam.close()
        a0.accept()


# -------------------- main --------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())