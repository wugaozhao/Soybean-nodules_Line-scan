import sys
import os
from datetime import datetime
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import cv2
import numpy as np
import time

try:
    from pypylon import pylon

    BASLER_AVAILABLE = True
except:
    BASLER_AVAILABLE = False
    print("警告: Basler相机库未安装，将无法使用Basler相机功能")


class SimpleBaslerCamera(QThread):
    """简化的Basler相机线程类 - 仅采集图像"""
    new_frame = pyqtSignal(np.ndarray)
    camera_error = pyqtSignal(str)
    camera_info = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.camera = None
        self.running = False

    def connect_camera(self):
        """连接Basler相机 - 最简单的连接方式"""
        try:
            # 获取传输层工厂
            tl_factory = pylon.TlFactory.GetInstance()

            # 查找所有设备
            devices = tl_factory.EnumerateDevices()

            if len(devices) == 0:
                self.camera_error.emit("未找到Basler相机，请检查连接")
                return False

            device_info = f"找到 {len(devices)} 个Basler相机设备"
            self.camera_info.emit(device_info)

            # 选择第一个设备
            self.camera = pylon.InstantCamera(tl_factory.CreateDevice(devices[0]))

            # 以最简单的方式打开相机 - 不设置任何参数
            self.camera.Open()

            # 获取相机信息
            try:
                model_name = self.camera.DeviceModelName.GetValue()
                serial_number = self.camera.DeviceSerialNumber.GetValue()
                self.camera_info.emit(f"已连接到相机: {model_name}\n序列号: {serial_number}")
            except:
                self.camera_info.emit("已连接到相机")

            # 开始采集图像
            self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

            return True

        except Exception as e:
            error_msg = f"相机连接失败: {str(e)}"
            self.camera_error.emit(error_msg)
            return False

    def run(self):
        """线程运行函数"""
        if not self.connect_camera():
            return

        self.running = True
        print("相机线程开始运行...")

        while self.running:
            try:
                # 获取图像，设置超时时间
                grab_result = self.camera.RetrieveResult(1000, pylon.TimeoutHandling_Return)

                if grab_result and grab_result.GrabSucceeded():
                    # 转换图像格式
                    img = grab_result.Array
                    grab_result.Release()

                    # 发送新帧
                    self.new_frame.emit(img)
                else:
                    # 如果没有获取到图像，稍作等待
                    time.sleep(0.01)

            except Exception as e:
                print(f"图像采集错误: {str(e)}")
                time.sleep(0.1)  # 短暂休眠避免CPU占用过高

    def stop(self):
        """停止相机"""
        self.running = False
        if self.isRunning():
            self.wait(1000)  # 等待线程结束，最多1秒

        if self.camera:
            try:
                if self.camera.IsGrabbing():
                    self.camera.StopGrabbing()
                self.camera.Close()
                print("相机已关闭")
            except Exception as e:
                print(f"关闭相机时出错: {str(e)}")
            finally:
                self.camera = None


class SimpleBaslerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.camera = None
        self.current_image = None
        self.zoom_factor = 1.0

        self.initUI()

        # 延迟启动相机，确保UI已初始化
        QTimer.singleShot(500, self.start_camera)

    def initUI(self):
        """初始化界面"""
        self.setWindowTitle('Basler相机拍摄程序 - 简化版')
        self.setGeometry(100, 100, 1200, 700)

        # 创建中心窗口
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QHBoxLayout(central_widget)

        # 创建可调整的分隔线
        self.splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.splitter)

        # 功能区（左侧）
        self.function_widget = QWidget()
        self.function_layout = QVBoxLayout(self.function_widget)

        # 相机状态显示
        status_group = QGroupBox("相机状态")
        status_layout = QVBoxLayout()

        self.camera_status_label = QLabel("正在初始化相机...")
        self.camera_status_label.setAlignment(Qt.AlignCenter)
        self.camera_status_label.setStyleSheet("font-weight: bold; padding: 5px; background-color: #FFFFCC;")

        self.camera_info_label = QLabel("")
        self.camera_info_label.setAlignment(Qt.AlignLeft)
        self.camera_info_label.setStyleSheet("padding: 5px; font-size: 10pt;")
        self.camera_info_label.setWordWrap(True)

        status_layout.addWidget(self.camera_status_label)
        status_layout.addWidget(self.camera_info_label)
        status_group.setLayout(status_layout)
        self.function_layout.addWidget(status_group)

        # 文件存储位置
        file_group = QGroupBox("文件存储位置")
        file_layout = QVBoxLayout()

        file_path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("点击浏览选择存储路径...")
        self.browse_btn = QPushButton("浏览")
        self.browse_btn.clicked.connect(self.browse_path)
        file_path_layout.addWidget(self.path_edit)
        file_path_layout.addWidget(self.browse_btn)

        file_layout.addLayout(file_path_layout)
        file_group.setLayout(file_layout)
        self.function_layout.addWidget(file_group)

        # 拍摄控制
        shoot_group = QGroupBox("拍摄控制")
        shoot_layout = QVBoxLayout()

        # 编号输入
        number_layout = QHBoxLayout()
        number_layout.addWidget(QLabel("编号:"))
        self.number_edit = QLineEdit()
        self.number_edit.setPlaceholderText("输入图像编号")
        self.number_edit.returnPressed.connect(self.start_shooting)
        number_layout.addWidget(self.number_edit)

        # 按钮
        button_layout = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.start_shooting)
        self.cancel_btn.clicked.connect(self.cancel_shooting)

        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.ok_btn)

        shoot_layout.addLayout(number_layout)
        shoot_layout.addLayout(button_layout)
        shoot_group.setLayout(shoot_layout)
        self.function_layout.addWidget(shoot_group)

        # 添加弹性空间
        self.function_layout.addStretch()

        # 图像预览区（右侧）
        self.preview_widget = QWidget()
        preview_layout = QVBoxLayout(self.preview_widget)

        # 预览标签
        self.preview_label = QLabel("等待相机连接...")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background-color: black; color: white; font-size: 14pt;")
        self.preview_label.setMinimumSize(640, 480)

        # 缩放控制
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("缩放:"))
        self.zoom_combo = QComboBox()
        self.zoom_combo.addItems(["25%", "50%", "75%", "100%", "125%", "150%", "200%"])
        self.zoom_combo.setCurrentIndex(3)
        self.zoom_combo.currentTextChanged.connect(self.change_zoom)
        zoom_layout.addWidget(self.zoom_combo)
        zoom_layout.addStretch()

        preview_layout.addLayout(zoom_layout)
        preview_layout.addWidget(self.preview_label)

        # 状态栏
        self.status_label = QLabel("就绪")
        preview_layout.addWidget(self.status_label)

        # 添加到分隔器
        self.splitter.addWidget(self.function_widget)
        self.splitter.addWidget(self.preview_widget)

        # 设置分隔器初始比例
        self.splitter.setSizes([300, 900])

        # 初始化默认路径
        self.init_default_path()

    def init_default_path(self):
        """初始化默认存储路径"""
        today = datetime.now().strftime("%m%d")
        default_path = f"C:/DATE-{today}"

        if not os.path.exists(default_path):
            try:
                os.makedirs(default_path)
            except:
                default_path = "C:/"

        self.path_edit.setText(default_path)

    def browse_path(self):
        """浏览选择存储路径"""
        path = QFileDialog.getExistingDirectory(self, "选择存储路径", self.path_edit.text())
        if path:
            self.path_edit.setText(path)

    def start_camera(self):
        """启动相机"""
        if not BASLER_AVAILABLE:
            QMessageBox.critical(self, "错误", "Basler相机库未安装，请安装pypylon库")
            self.camera_status_label.setText("Basler相机库未安装")
            return

        self.camera = SimpleBaslerCamera()
        self.camera.new_frame.connect(self.update_preview)
        self.camera.camera_error.connect(self.handle_camera_error)
        self.camera.camera_info.connect(self.update_camera_info)
        self.camera.start()

    def update_camera_info(self, info):
        """更新相机信息"""
        self.camera_info_label.setText(info)
        self.camera_status_label.setText("相机已连接")
        self.camera_status_label.setStyleSheet(
            "color: green; font-weight: bold; padding: 5px; background-color: #CCFFCC;")
        self.preview_label.setText("正在采集图像...")

    def handle_camera_error(self, error_msg):
        """处理相机错误"""
        self.status_label.setText(f"相机错误")
        self.camera_status_label.setText("相机连接失败")
        self.camera_status_label.setStyleSheet(
            "color: red; font-weight: bold; padding: 5px; background-color: #FFCCCC;")
        self.preview_label.setText("相机未连接")

        # 显示详细错误信息
        QMessageBox.warning(self, "相机错误", error_msg)

    def update_preview(self, frame):
        """更新预览图像"""
        self.current_image = frame

        # 转换图像格式
        if len(frame.shape) == 3:
            # 如果是彩色图像，BGR转RGB
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        else:
            # 如果是灰度图像，转换为RGB
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)

        # 调整大小
        height, width = rgb_image.shape[:2]
        new_width = int(width * self.zoom_factor)
        new_height = int(height * self.zoom_factor)

        if self.zoom_factor != 1.0:
            rgb_image = cv2.resize(rgb_image, (new_width, new_height))

        # 转换为QPixmap
        bytes_per_line = 3 * new_width
        q_image = QImage(rgb_image.data, new_width, new_height, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)

        # 更新标签
        self.preview_label.setPixmap(pixmap)
        self.preview_label.setScaledContents(True)

    def change_zoom(self, zoom_text):
        """改变缩放比例"""
        zoom_percent = int(zoom_text.rstrip('%'))
        self.zoom_factor = zoom_percent / 100.0

    def start_shooting(self):
        """开始拍摄"""
        if not self.camera or not self.camera.running:
            QMessageBox.warning(self, "警告", "相机未连接，无法拍摄")
            return

        number = self.number_edit.text().strip()
        if not number:
            QMessageBox.warning(self, "警告", "请输入编号")
            return

        if self.current_image is None:
            QMessageBox.warning(self, "警告", "没有可保存的图像")
            return

        # 获取存储路径
        save_path = self.path_edit.text().strip()
        if not save_path:
            QMessageBox.warning(self, "警告", "请选择存储路径")
            return

        # 确保路径存在
        if not os.path.exists(save_path):
            try:
                os.makedirs(save_path)
            except:
                QMessageBox.warning(self, "错误", f"无法创建目录: {save_path}")
                return

        # 生成文件名
        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"{number}_{timestamp}.png"  # 使用PNG格式保持高质量
        filepath = os.path.join(save_path, filename)

        # 保存图像
        try:
            # 保存图像
            cv2.imwrite(filepath, self.current_image)

            self.status_label.setText(f"已保存: {filename}")

            # 清空编号输入框
            self.number_edit.clear()

            QMessageBox.information(self, "保存成功", f"图像已保存到:\n{filepath}")

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法保存图像: {str(e)}")

    def cancel_shooting(self):
        """取消拍摄"""
        self.number_edit.clear()
        self.status_label.setText("拍摄已取消")

    def closeEvent(self, event):
        """关闭事件"""
        if self.camera:
            self.camera.stop()

        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # 使用Fusion风格

    # 设置应用程序图标和字体
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    window = SimpleBaslerApp()
    window.show()

    sys.exit(app.exec_())