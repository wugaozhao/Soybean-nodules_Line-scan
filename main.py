# -*- coding: utf-8 -*-

import os
import json
import ipaddress
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime

import numpy as np
import serial
import serial.tools.list_ports
from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QComboBox,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from test.camera_3 import CameraThread, ImageSynthesizer


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAMERA_NETWORK_CONFIG = os.path.join(BASE_DIR, "config", "camera_network.json")
CAMERA_PARAMS_CONFIG = os.path.join(BASE_DIR, "config", "camera_params.json")

DEFAULT_CAMERA_PARAMS = {
    "line_frequency": 2000,
    "feature_file": "",
    "rgb_exposure": {
        "red": 900,
        "green": 900,
        "blue": 900,
    },
}


def load_camera_params_config():
    config = json.loads(json.dumps(DEFAULT_CAMERA_PARAMS))
    if not os.path.exists(CAMERA_PARAMS_CONFIG):
        return config

    try:
        with open(CAMERA_PARAMS_CONFIG, "r", encoding="utf-8") as fh:
            user_config = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return config

    if isinstance(user_config, dict):
        if "line_frequency" in user_config:
            config["line_frequency"] = user_config["line_frequency"]
        if "feature_file" in user_config:
            config["feature_file"] = user_config["feature_file"]
        if isinstance(user_config.get("rgb_exposure"), dict):
            config["rgb_exposure"].update(user_config["rgb_exposure"])
    return config


class SerialReaderThread(QThread):
    line_received = pyqtSignal(str)
    error_received = pyqtSignal(str)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.is_running = True

    def run(self):
        while self.is_running and self.serial_port and self.serial_port.is_open:
            try:
                raw = self.serial_port.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    self.line_received.emit(line)
            except Exception as exc:
                self.error_received.emit(f"串口接收异常: {exc}")
                break

    def stop(self):
        self.is_running = False
        self.wait(1500)


class ImageSaveThread(QThread):
    saved = pyqtSignal(str, int, int, int, float, str)
    no_data = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, frames, file_name, save_dir, reason, capture_start_time, frame_count, total_height):
        super().__init__()
        self.frames = frames
        self.file_name = file_name
        self.save_dir = save_dir
        self.reason = reason
        self.capture_start_time = capture_start_time
        self.frame_count = frame_count
        self.total_height = total_height

    def run(self):
        try:
            if not self.frames:
                self.no_data.emit()
                return

            from PIL import Image

            os.makedirs(self.save_dir, exist_ok=True)
            combined_img = np.vstack(self.frames)
            if combined_img.shape[-1] == 1:
                combined_img = combined_img.squeeze(axis=-1)

            if combined_img is None or combined_img.size == 0:
                self.no_data.emit()
                return

            if len(combined_img.shape) == 2:
                img = Image.fromarray(combined_img.astype(np.uint8), mode="L")
            elif len(combined_img.shape) == 3 and combined_img.shape[2] == 3:
                img = Image.fromarray(combined_img.astype(np.uint8), mode="RGB")
            else:
                img = Image.fromarray(combined_img.squeeze().astype(np.uint8), mode="L")

            full_path = os.path.join(self.save_dir, f"{self.file_name}.bmp")
            img.save(full_path)

            elapsed = 0
            if self.capture_start_time is not None:
                elapsed = max(time.monotonic() - self.capture_start_time, 0.001)
            actual_line_rate = self.total_height / elapsed if elapsed else 0
            width = combined_img.shape[1]
            self.saved.emit(full_path, self.frame_count, self.total_height, width, actual_line_rate, self.reason)
        except ImportError:
            self.error.emit("错误: 请安装 Pillow: pip install Pillow")
        except Exception as exc:
            self.error.emit(f"保存图像失败: {exc}\n{traceback.format_exc()}")


def load_camera_network_config():
    default_config = {
        "adapter_name": "以太网",
        "pc_ip": "169.254.32.100",
        "subnet_mask": "255.255.0.0",
        "camera_ip": "169.254.32.1",
        "enum_timeout_ms": 200,
        "auto_configure": False,
    }
    try:
        with open(CAMERA_NETWORK_CONFIG, "r", encoding="utf-8") as f:
            config = json.load(f)
        default_config.update(config)
    except FileNotFoundError:
        pass
    except Exception as exc:
        default_config["config_error"] = str(exc)
    return default_config


def subnet_mask_to_prefix(mask):
    return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen


def get_adapter_ipv4_addresses(adapter_name):
    command = (
        "Get-NetIPAddress -AddressFamily IPv4 "
        f"-InterfaceAlias '{adapter_name}' -ErrorAction SilentlyContinue | "
        "Select-Object IPAddress,PrefixLength,AddressState | ConvertTo-Json"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    data = json.loads(result.stdout)
    if isinstance(data, dict):
        data = [data]
    return data


def check_camera_network_config():
    config = load_camera_network_config()
    messages = []

    if "config_error" in config:
        messages.append(f"读取相机网络配置失败: {config['config_error']}")
        return False, config, messages

    adapter_name = config["adapter_name"]
    expected_ip = config["pc_ip"]
    expected_prefix = subnet_mask_to_prefix(config["subnet_mask"])
    camera_ip = ipaddress.IPv4Address(config["camera_ip"])
    camera_network = ipaddress.IPv4Network(
        f"{expected_ip}/{config['subnet_mask']}", strict=False
    )

    if camera_ip not in camera_network:
        messages.append(
            f"配置错误: 相机IP {camera_ip} 不在电脑网段 {camera_network} 内"
        )
        return False, config, messages

    try:
        addresses = get_adapter_ipv4_addresses(adapter_name)
    except Exception as exc:
        messages.append(f"读取网卡 {adapter_name} IPv4 配置失败: {exc}")
        return False, config, messages

    for item in addresses:
        if (
            item.get("IPAddress") == expected_ip
            and int(item.get("PrefixLength", -1)) == expected_prefix
        ):
            return True, config, messages

    current = ", ".join(
        f"{item.get('IPAddress')}/{item.get('PrefixLength')}"
        for item in addresses
    ) or "未配置IPv4"
    messages.append(
        f"相机网卡配置不匹配: {adapter_name} 当前为 {current}, "
        f"应为 {expected_ip}/{expected_prefix}"
    )
    messages.append(
        "请用管理员PowerShell执行: "
        f'powershell -ExecutionPolicy Bypass -File "{os.path.join(BASE_DIR, "tools", "configure_camera_network.ps1")}"'
    )
    return False, config, messages


class IntegratedWindow(QMainWindow):
    DIRECTION_NEAR_MOTOR = 1
    DIRECTION_FAR_MOTOR = 0

    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.serial_thread = None
        self.camera_thread = None
        self.synthesizer = ImageSynthesizer()

        self.is_capturing = False
        self.motor_running = False
        self.finishing_capture = False
        self.returning_home = False
        self.manual_motion_mode = None
        self.active_motion_direction = None
        self.current_file_name = ""
        self.capture_start_time = None
        self.camera_params = load_camera_params_config()
        self.target_line_frequency = int(self.camera_params.get("line_frequency", 2000))
        self.home_return_freq = 2500
        self.save_threads = []

        self.upper_active = None
        self.lower_active = None
        self.last_stop_reason = ""

        self.output_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
        self.using_default_save_dir = True
        self.save_dir = self.default_daily_save_dir()
        os.makedirs(self.save_dir, exist_ok=True)

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(500)
        self.status_timer.timeout.connect(self.query_motor_status)

        self.init_ui()
        self.refresh_ports()
        self.update_control_states()

    def init_ui(self):
        self.setWindowTitle("大豆根瘤线扫描拍摄系统")
        self.setGeometry(80, 80, 1250, 820)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        self.upper_limit_labels = []
        self.lower_limit_labels = []
        self.motor_status_labels = []
        self.port_combos = []
        self.baud_combos = []
        self.connect_buttons = []
        self.refresh_buttons = []

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self.create_capture_tab(), "联动拍摄")
        self.tabs.addTab(self.create_debug_tab(), "设备调试")

        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(170)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

    def create_capture_tab(self):
        tab = QWidget()
        main_layout = QHBoxLayout(tab)

        left_panel = QWidget()
        left_panel.setMinimumWidth(380)
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(self.create_serial_group())
        left_layout.addWidget(self.create_limit_group())

        param_group = QGroupBox("拍摄与运动参数")
        param_layout = QFormLayout()
        param_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        param_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.line_frequency_input = QLineEdit(str(self.target_line_frequency))
        self.motor_freq_spin = QSpinBox()
        self.motor_freq_spin.setRange(1, 20000)
        self.motor_freq_spin.setValue(1000)
        self.motor_freq_spin.setSuffix(" Hz")
        self.accel_spin = QSpinBox()
        self.accel_spin.setRange(0, 5000)
        self.accel_spin.setValue(500)
        self.accel_spin.setSuffix(" ms")
        self.decel_spin = QSpinBox()
        self.decel_spin.setRange(0, 5000)
        self.decel_spin.setValue(500)
        self.decel_spin.setSuffix(" ms")
        self.max_pulses_spin = QSpinBox()
        self.max_pulses_spin.setRange(1, 2000000000)
        self.max_pulses_spin.setValue(999999)
        self.down_dir_combo = QComboBox()
        self.down_dir_combo.addItem("D0：远离电机端", self.DIRECTION_FAR_MOTOR)
        self.apply_params_btn = QPushButton("应用参数")
        self.apply_params_btn.clicked.connect(self.apply_params)

        for widget in (
            self.line_frequency_input,
            self.motor_freq_spin,
            self.accel_spin,
            self.decel_spin,
            self.max_pulses_spin,
            self.down_dir_combo,
        ):
            widget.setMinimumWidth(170)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        param_layout.addRow("相机行频", self.line_frequency_input)
        param_layout.addRow("电机频率", self.motor_freq_spin)
        param_layout.addRow("加速时间", self.accel_spin)
        param_layout.addRow("减速时间", self.decel_spin)
        param_layout.addRow("最大保护脉冲", self.max_pulses_spin)
        param_layout.addRow("扫描方向", self.down_dir_combo)
        param_layout.addRow(self.apply_params_btn)
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

        control_group = QGroupBox("联动控制")
        control_layout = QVBoxLayout()
        self.init_cam_btn = QPushButton("初始化相机")
        self.init_cam_btn.clicked.connect(self.init_camera)
        self.start_btn = QPushButton("开始拍摄")
        self.start_btn.clicked.connect(self.start_capture)
        self.stop_btn = QPushButton("停止并保存")
        self.stop_btn.clicked.connect(self.manual_stop)
        self.home_btn = QPushButton("回上限位")
        self.home_btn.clicked.connect(self.manual_return_home)
        control_layout.addWidget(self.init_cam_btn)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.home_btn)
        control_layout.addWidget(self.stop_btn)
        control_group.setLayout(control_layout)
        left_layout.addWidget(control_group)

        info_group = QGroupBox("设备信息")
        info_layout = QVBoxLayout()
        self.info_label = QLabel("相机未初始化")
        self.info_label.setWordWrap(True)
        info_layout.addWidget(self.info_label)
        info_group.setLayout(info_layout)
        left_layout.addWidget(info_group)
        left_layout.addStretch()

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(400)
        left_scroll.setMaximumWidth(480)
        left_scroll.setWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        preview_group = QGroupBox("图像预览")
        preview_layout = QVBoxLayout()
        self.preview_label = QLabel("等待图像...")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(700, 520)
        self.preview_label.setStyleSheet("background-color: black; color: white;")
        preview_layout.addWidget(self.preview_label)
        preview_group.setLayout(preview_layout)
        right_layout.addWidget(preview_group, 1)

        main_layout.addWidget(left_scroll)
        main_layout.addWidget(right_panel, 1)
        return tab

    def create_serial_group(self):
        serial_group = QGroupBox("Arduino 串口")
        serial_layout = QVBoxLayout()
        serial_row = QHBoxLayout()
        port_combo = QComboBox()
        baud_combo = QComboBox()
        baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        baud_combo.setCurrentText("9600")
        serial_row.addWidget(QLabel("端口"))
        serial_row.addWidget(port_combo, 1)
        serial_row.addWidget(QLabel("波特率"))
        serial_row.addWidget(baud_combo)
        serial_layout.addLayout(serial_row)

        serial_btn_row = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh_ports)
        connect_btn = QPushButton("连接")
        connect_btn.clicked.connect(self.toggle_serial)
        serial_btn_row.addWidget(refresh_btn)
        serial_btn_row.addWidget(connect_btn)
        serial_layout.addLayout(serial_btn_row)

        self.port_combos.append(port_combo)
        self.baud_combos.append(baud_combo)
        self.refresh_buttons.append(refresh_btn)
        self.connect_buttons.append(connect_btn)

        serial_group.setLayout(serial_layout)
        return serial_group

    def create_debug_tab(self):
        tab = QWidget()
        main_layout = QHBoxLayout(tab)

        left_panel = QWidget()
        left_panel.setFixedWidth(420)
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(self.create_serial_group())

        left_layout.addWidget(self.create_limit_group())

        debug_param_group = QGroupBox("电机调试参数")
        debug_param_layout = QFormLayout()
        self.debug_freq_spin = QSpinBox()
        self.debug_freq_spin.setRange(1, 20000)
        self.debug_freq_spin.setValue(500)
        self.debug_freq_spin.setSuffix(" Hz")
        self.debug_pulses_spin = QSpinBox()
        self.debug_pulses_spin.setRange(1, 2000000000)
        self.debug_pulses_spin.setValue(10000)
        self.debug_dir_combo = QComboBox()
        self.debug_dir_combo.addItem("D0：远离电机端", self.DIRECTION_FAR_MOTOR)
        self.debug_dir_combo.addItem("D1：靠近电机端", self.DIRECTION_NEAR_MOTOR)
        self.debug_dir_combo.currentIndexChanged.connect(self.update_control_states)
        self.apply_debug_params_btn = QPushButton("应用调试参数")
        self.apply_debug_params_btn.clicked.connect(lambda: self.apply_debug_motor_params())

        debug_param_layout.addRow("脉冲频率", self.debug_freq_spin)
        debug_param_layout.addRow("脉冲数量", self.debug_pulses_spin)
        debug_param_layout.addRow("当前方向", self.debug_dir_combo)
        debug_param_layout.addRow(self.apply_debug_params_btn)
        debug_param_group.setLayout(debug_param_layout)
        left_layout.addWidget(debug_param_group)

        debug_control_group = QGroupBox("手动运动")
        debug_control_layout = QVBoxLayout()
        self.debug_move_down_btn = QPushButton("远离电机端运动")
        self.debug_move_down_btn.clicked.connect(self.debug_move_down)
        self.debug_move_up_btn = QPushButton("靠近电机端运动")
        self.debug_move_up_btn.clicked.connect(self.debug_move_up)
        self.debug_jog_dir_btn = QPushButton("按当前方向运动")
        self.debug_jog_dir_btn.clicked.connect(self.debug_jog_selected_dir)
        self.debug_stop_btn = QPushButton("停止运动")
        self.debug_stop_btn.clicked.connect(self.debug_stop_motor)
        debug_control_layout.addWidget(self.debug_move_down_btn)
        debug_control_layout.addWidget(self.debug_move_up_btn)
        debug_control_layout.addWidget(self.debug_jog_dir_btn)
        debug_control_layout.addWidget(self.debug_stop_btn)
        debug_control_group.setLayout(debug_control_layout)
        left_layout.addWidget(debug_control_group)
        left_layout.addStretch()

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        serial_note = QLabel(
            "方向定义：D1=靠近电机端/上限位方向，D0=远离电机端/下限位方向。"
        )
        serial_note.setWordWrap(True)
        right_layout.addWidget(serial_note)
        right_layout.addStretch()

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1)
        return tab

    def create_limit_group(self):
        limit_group = QGroupBox("限位状态")
        limit_layout = QFormLayout()
        upper_label = QLabel("未知")
        lower_label = QLabel("未知")
        motor_label = QLabel("未连接")
        self.upper_limit_labels.append(upper_label)
        self.lower_limit_labels.append(lower_label)
        self.motor_status_labels.append(motor_label)
        limit_layout.addRow("上限位", upper_label)
        limit_layout.addRow("下限位", lower_label)
        limit_layout.addRow("模组状态", motor_label)
        limit_group.setLayout(limit_layout)
        return limit_group

    def refresh_ports(self):
        current_values = [combo.currentText().split(" - ")[0] for combo in self.port_combos]
        ports = list(serial.tools.list_ports.comports())
        for combo_index, combo in enumerate(self.port_combos):
            combo.blockSignals(True)
            combo.clear()
            for port in ports:
                combo.addItem(f"{port.device} - {port.description}")
            current = current_values[combo_index] if combo_index < len(current_values) else ""
            if current:
                index = combo.findText(current, Qt.MatchStartsWith)
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.blockSignals(False)

        if self.port_combos and self.port_combos[0].currentText():
            selected_port = self.port_combos[0].currentText().split(" - ")[0]
            self.sync_serial_port_selection(selected_port)

    def toggle_serial(self):
        if self.serial_port and self.serial_port.is_open:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        port_combo, baud_combo = self.active_serial_controls()
        if port_combo is None or not port_combo.currentText():
            QMessageBox.warning(self, "串口", "未找到可用串口")
            return
        try:
            port_name = port_combo.currentText().split(" - ")[0]
            baud_rate = int(baud_combo.currentText())
            self.serial_port = serial.Serial(port_name, baud_rate, timeout=0.2)
            self.serial_thread = SerialReaderThread(self.serial_port)
            self.serial_thread.line_received.connect(self.handle_serial_line)
            self.serial_thread.error_received.connect(self.log)
            self.serial_thread.start()
            self.sync_serial_port_selection(port_name)
            self.sync_baud_selection(str(baud_rate))
            self.set_connect_button_text("断开")
            self.log(f"已连接 Arduino: {port_name}, {baud_rate}")
            self.status_timer.start()
            QTimer.singleShot(1800, self.sync_motor_params)
            self.update_control_states()
        except Exception as exc:
            QMessageBox.critical(self, "串口连接失败", str(exc))
            self.serial_port = None
            self.serial_thread = None
            self.update_control_states()

    def disconnect_serial(self):
        self.status_timer.stop()
        if self.is_capturing or self.motor_running:
            self.send_command("S", log_send=True)
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.serial_port = None
        self.set_connect_button_text("连接")
        self.upper_active = None
        self.lower_active = None
        self.motor_running = False
        self.returning_home = False
        self.set_motor_status("未连接")
        self.update_limit_labels()
        self.update_control_states()
        self.log("Arduino 串口已断开")

    def active_serial_controls(self):
        tab_index = self.tabs.currentIndex() if hasattr(self, "tabs") else 0
        if tab_index < len(self.port_combos):
            return self.port_combos[tab_index], self.baud_combos[tab_index]
        if self.port_combos:
            return self.port_combos[0], self.baud_combos[0]
        return None, None

    def sync_serial_port_selection(self, port_name):
        for combo in self.port_combos:
            index = combo.findText(port_name, Qt.MatchStartsWith)
            if index >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)

    def sync_baud_selection(self, baud_rate):
        for combo in self.baud_combos:
            index = combo.findText(baud_rate)
            if index >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)

    def set_connect_button_text(self, text):
        for button in self.connect_buttons:
            button.setText(text)

    def send_command(self, command, log_send=True):
        if not self.serial_port or not self.serial_port.is_open:
            if log_send:
                self.log("串口未连接，无法发送指令")
            return False
        try:
            self.serial_port.write((command + "\n").encode("utf-8"))
            if log_send and command != "R":
                self.log(f">> {command}")
            return True
        except Exception as exc:
            self.log(f"发送指令失败: {exc}")
            return False

    def sync_motor_params(self):
        if not self.serial_port or not self.serial_port.is_open:
            return
        self.send_command(f"D{self.DIRECTION_FAR_MOTOR}")
        self.send_command(f"F{self.motor_freq_spin.value()}")
        self.send_command(f"A{self.accel_spin.value()}")
        self.send_command(f"B{self.decel_spin.value()}")
        self.send_command(f"M{self.max_pulses_spin.value()}")
        self.query_motor_status()

    def send_motion_params(self, direction, frequency):
        if not self.serial_port or not self.serial_port.is_open:
            self.log("串口未连接，无法发送运动参数")
            return False
        ok1 = self.send_command(f"D{direction}")
        ok2 = self.send_command(f"F{frequency}")
        return ok1 and ok2

    def is_direction_blocked_by_limit(self, direction):
        if direction == self.DIRECTION_NEAR_MOTOR and self.upper_active:
            return "上限位已触发，不能继续靠近电机端运动；请改用 D0 远离电机端"
        if direction == self.DIRECTION_FAR_MOTOR and self.lower_active:
            return "下限位已触发，不能继续远离电机端运动；请改用 D1 靠近电机端"
        return ""

    def start_p_motion(self, direction, frequency, pulses):
        blocked_reason = self.is_direction_blocked_by_limit(direction)
        if blocked_reason:
            self.log(blocked_reason)
            return False
        if not self.send_motion_params(direction, frequency):
            return False
        return self.send_command(f"P{pulses}")

    def direction_name(self, direction):
        return "远离电机端" if direction == self.DIRECTION_FAR_MOTOR else "靠近电机端"

    def query_motor_status(self):
        self.send_command("R", log_send=False)

    def handle_serial_line(self, line):
        if line.startswith("STATUS:"):
            self.parse_status(line)
            return

        self.log(f"<< {line}")

        if line == "EVENT:RUN_STARTED":
            self.motor_running = True
            if self.manual_motion_mode == "DOWN":
                self.set_motor_status("调试远离电机端运动中")
            else:
                self.set_motor_status("拍摄运动：远离电机端")
            self.update_control_states()
            return

        if line == "EVENT:HOMING_STARTED":
            self.returning_home = True
            self.motor_running = True
            if self.manual_motion_mode == "UP":
                self.set_motor_status("调试靠近电机端运动中")
            else:
                self.set_motor_status("回上限位：靠近电机端")
            self.update_control_states()
            return

        if line == "EVENT:DEBUG_STARTED":
            self.motor_running = True
            if self.manual_motion_mode == "UP":
                self.set_motor_status("调试靠近电机端运动中")
            elif self.manual_motion_mode == "DOWN":
                self.set_motor_status("调试远离电机端运动中")
            else:
                self.set_motor_status("调试运动中")
            self.update_control_states()
            return

        if line == "EVENT:POWER_ON_HOMING_PENDING":
            self.returning_home = True
            self.motor_running = False
            self.set_motor_status("等待上电自动回上限位")
            self.update_control_states()
            return

        if line == "EVENT:POWER_ON_UPPER_READY":
            self.returning_home = False
            self.motor_running = False
            self.upper_active = True
            self.lower_active = False
            self.update_limit_labels()
            self.set_motor_status("已在上限位，等待下一次拍摄")
            self.update_control_states()
            return

        if line == "EVENT:LOWER_LIMIT":
            self.lower_active = True
            self.upper_active = False
            self.motor_running = False
            self.active_motion_direction = None
            self.last_stop_reason = "下限位触发"
            self.update_limit_labels()
            if self.is_capturing:
                self.finish_capture(save_image=True, reason="下限位触发", send_stop=False)
            else:
                self.manual_motion_mode = None
                self.set_motor_status("已到下限位")
                self.update_control_states()
            return

        if line == "EVENT:UPPER_LIMIT":
            self.upper_active = True
            self.lower_active = False
            self.motor_running = False
            self.active_motion_direction = None
            self.last_stop_reason = "上限位触发"
            self.update_limit_labels()
            if self.returning_home:
                self.returning_home = False
                self.manual_motion_mode = None
                self.set_motor_status("已回到上限位，等待下一次拍摄")
                self.log("模组已回到上限位，等待下一次拍摄指令")
                self.update_control_states()
            else:
                self.manual_motion_mode = None
                self.set_motor_status("已到上限位")
                self.update_control_states()
            return

        if line == "EVENT:MAX_PULSES":
            self.motor_running = False
            self.active_motion_direction = None
            self.last_stop_reason = "达到最大保护脉冲"
            if self.manual_motion_mode:
                self.manual_motion_mode = None
                self.returning_home = False
                self.set_motor_status("调试运动停止：达到脉冲数量")
                self.update_control_states()
                return
            if self.returning_home:
                self.returning_home = False
                self.manual_motion_mode = None
                self.set_motor_status("回上限位失败：达到最大保护脉冲")
                self.log("回上限位失败：达到最大保护脉冲但未触发上限位，请检查方向、限位传感器和最大保护脉冲")
                self.update_control_states()
                return
            self.finish_capture(save_image=True, reason="达到最大保护脉冲", send_stop=False)
            return

        if line == "EVENT:STOPPED":
            self.motor_running = False
            self.returning_home = False
            self.manual_motion_mode = None
            self.active_motion_direction = None
            self.set_motor_status("已停止")
            self.update_control_states()
            return

        if line == "EVENT:DONE":
            self.motor_running = False
            self.active_motion_direction = None
            self.last_stop_reason = "达到设定脉冲数量"
            if self.manual_motion_mode:
                self.manual_motion_mode = None
                self.returning_home = False
                self.set_motor_status("调试运动停止：达到设定脉冲数量")
                self.update_control_states()
                return
            if self.returning_home:
                self.returning_home = False
                self.manual_motion_mode = None
                self.set_motor_status("回上限位停止：达到设定脉冲数量")
                self.log("回上限位已达到设定脉冲数量；如未触发上限位，请检查方向和脉冲数")
                self.update_control_states()
                return
            if self.is_capturing:
                self.finish_capture(save_image=True, reason="达到设定脉冲数量", send_stop=False)
                return
            self.set_motor_status("已完成设定脉冲运动")
            self.update_control_states()
            return

        if line.startswith("ERR:") and self.is_capturing:
            self.finish_capture(save_image=False, reason=f"Arduino 返回错误: {line}", send_stop=True)
            return

        if line.startswith("ERR:") and self.manual_motion_mode:
            self.manual_motion_mode = None
            self.motor_running = False
            self.returning_home = False
            self.active_motion_direction = None
            self.set_motor_status(f"调试运动失败: {line}")
            self.log(f"调试运动失败，Arduino 返回: {line}")
            self.update_control_states()
            return

        if line.startswith("ERR:") and self.returning_home:
            if line == "ERR:UPPER_ALREADY_ACTIVE":
                self.returning_home = False
                self.motor_running = False
                self.manual_motion_mode = None
                self.active_motion_direction = None
                if self.upper_active is True:
                    self.update_limit_labels()
                    self.set_motor_status("已在上限位，等待下一次拍摄")
                    self.log("Arduino 提示上限位已触发，回程完成")
                else:
                    self.set_motor_status("回上限位启动失败：Arduino 误报上限位已触发")
                    self.log("Arduino 返回 ERR:UPPER_ALREADY_ACTIVE，但当前状态未显示上限位触发；已停止回程并重新查询限位状态")
                    self.query_motor_status()
            else:
                self.returning_home = False
                self.motor_running = False
                self.manual_motion_mode = None
                self.active_motion_direction = None
                self.set_motor_status(f"回上限位失败: {line}")
                self.log(f"回上限位失败，请检查模组: {line}")
            self.update_control_states()
            return

    def parse_status(self, line):
        try:
            payload = line[len("STATUS:"):]
            parts = {}
            for item in payload.split(";"):
                if ":" in item:
                    key, value = item.split(":", 1)
                    parts[key] = value

            state = parts.get("STATE", "UNKNOWN")
            self.motor_running = state == "RUNNING"
            if "UPPER" in parts:
                self.upper_active = parts.get("UPPER") == "1"
            if "LOWER" in parts:
                self.lower_active = parts.get("LOWER") == "1"
            self.last_stop_reason = parts.get("REASON", self.last_stop_reason)

            pulses = parts.get("PULSES", "0")
            freq = parts.get("FREQ", "0")
            raw_text = ""
            if "URAW" in parts and "LRAW" in parts:
                raw_text = f"  原始电平 U:{parts['URAW']} L:{parts['LRAW']}"
            if self.motor_running and self.active_motion_direction == self.DIRECTION_NEAR_MOTOR and self.upper_active:
                self.log("检测到上限位已触发，发送停止指令")
                self.send_command("S")
            elif self.motor_running and self.active_motion_direction == self.DIRECTION_FAR_MOTOR and self.lower_active:
                self.log("检测到下限位已触发，发送停止指令")
                self.send_command("S")

            if self.returning_home and self.upper_active and not self.motor_running:
                self.returning_home = False
                self.active_motion_direction = None
                self.set_motor_status("已回到上限位，等待下一次拍摄")
                self.log("模组已回到上限位，等待下一次拍摄指令")
            elif self.returning_home:
                self.set_motor_status(f"回上限位：靠近电机端  脉冲:{pulses}  频率:{freq}Hz{raw_text}")
            elif self.is_capturing:
                self.set_motor_status(f"拍摄运动：远离电机端  脉冲:{pulses}  频率:{freq}Hz{raw_text}")
            else:
                self.set_motor_status(f"{state}  脉冲:{pulses}  频率:{freq}Hz{raw_text}")
            self.update_limit_labels()
            self.update_control_states()
        except Exception as exc:
            self.log(f"状态解析失败: {exc}")

    def update_limit_labels(self):
        for label in self.upper_limit_labels:
            self.set_limit_label(label, self.upper_active)
        for label in self.lower_limit_labels:
            self.set_limit_label(label, self.lower_active)

    def set_motor_status(self, text):
        for label in self.motor_status_labels:
            label.setText(text)

    @staticmethod
    def set_limit_label(label, active):
        if active is None:
            label.setText("未知")
            label.setStyleSheet("color: #666;")
        elif active:
            label.setText("触发")
            label.setStyleSheet("color: #d32f2f; font-weight: bold;")
        else:
            label.setText("未触发")
            label.setStyleSheet("color: #2e7d32; font-weight: bold;")

    def init_camera(self):
        try:
            self.log("正在初始化相机...")
            network_ok, network_config, network_messages = check_camera_network_config()
            for message in network_messages:
                self.log(message)
            if network_ok:
                self.log(
                    f"相机网络配置正常: {network_config['adapter_name']} "
                    f"{network_config['pc_ip']}/{network_config['subnet_mask']}, "
                    f"相机 {network_config['camera_ip']}"
                )
            else:
                self.info_label.setText("相机网络配置不匹配")
                return

            if self.camera_thread is not None:
                self.camera_thread.cleanup()
                self.camera_thread = None

            self.camera_thread = CameraThread()
            self.camera_thread.log_signal.connect(self.log)
            self.camera_thread.image_update.connect(self.update_preview)
            self.camera_thread.frame_received.connect(self.on_frame_received)

            if self.camera_thread.init_camera(device_index=0):
                if self.apply_camera_params(sync_motor=False):
                    self.log("相机配置文件参数已自动应用")
                self.info_label.setText("相机已就绪")
                self.log("相机初始化成功")
            else:
                self.info_label.setText("相机初始化失败")
                self.log("相机初始化失败")
                self.camera_thread = None
        except Exception as exc:
            self.info_label.setText("相机初始化异常")
            self.log(f"相机初始化异常: {exc}")
            traceback.print_exc()
        self.update_control_states()

    def apply_camera_params(self, sync_motor=True):
        ok = True
        if self.camera_thread is not None and not self.is_capturing:
            try:
                line_frequency = int(self.line_frequency_input.text())
                if line_frequency <= 0:
                    raise ValueError
                self.target_line_frequency = line_frequency
                self.camera_params = load_camera_params_config()
                feature_loaded = False
                feature_file = self.camera_params.get("feature_file")
                if feature_file:
                    if not os.path.isabs(feature_file):
                        feature_file = os.path.join(BASE_DIR, feature_file)
                    feature_loaded = self.camera_thread.load_feature_file(feature_file)
                    if not feature_loaded:
                        ok = False

                if self.camera_thread.set_line_scan_params(line_frequency=line_frequency):
                    self.log(f"相机行频已设置: {line_frequency} line/s")
                else:
                    ok = False
                    self.log("相机参数设置失败或部分失败")

                rgb = self.camera_params.get("rgb_exposure", {})
                red = int(rgb.get("red", 900))
                green = int(rgb.get("green", 900))
                blue = int(rgb.get("blue", 900))
                if self.camera_thread.set_rgb_exposure(
                    red=red,
                    green=green,
                    blue=blue,
                    nodes=rgb.get("nodes"),
                ):
                    self.log(f"RGB曝光/亮度已设置: R={red}, G={green}, B={blue}")
                else:
                    if feature_loaded:
                        self.log("RGB直接写入失败，沿用MVS特性文件中的RGB设置")
                    else:
                        ok = False
                        self.log("RGB曝光/亮度设置失败或部分失败")
            except ValueError:
                ok = False
                self.log("行频值错误，请输入大于 0 的整数")
            except Exception as exc:
                ok = False
                self.log(f"应用相机参数异常: {exc}")
                traceback.print_exc()

        if sync_motor and self.serial_port and self.serial_port.is_open:
            self.sync_motor_params()
        return ok

    def apply_params(self):
        return self.apply_camera_params(sync_motor=True)

    def default_daily_save_dir(self):
        return os.path.join(self.output_root, datetime.now().strftime("Date%m%d"))

    def refresh_default_save_dir(self):
        if not self.using_default_save_dir:
            return
        current_default = self.default_daily_save_dir()
        if self.save_dir != current_default:
            self.save_dir = current_default
            if hasattr(self, "save_path_label"):
                self.save_path_label.setText(f"当前路径:\n{self.save_dir}")
        os.makedirs(self.save_dir, exist_ok=True)

    def select_save_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存路径", self.save_dir)
        if path:
            self.using_default_save_dir = False
            self.save_dir = path
            self.save_path_label.setText(f"当前路径:\n{self.save_dir}")
            self.log(f"保存路径已更改为: {self.save_dir}")

    def start_capture(self):
        self.refresh_default_save_dir()
        if not self.serial_port or not self.serial_port.is_open:
            QMessageBox.warning(self, "无法开始", "请先连接 Arduino")
            return
        if self.camera_thread is None:
            QMessageBox.warning(self, "无法开始", "请先初始化相机")
            return
        if self.is_capturing:
            self.log("当前已在拍摄中")
            return
        if self.lower_active:
            QMessageBox.warning(self, "无法开始", "当前下限位已触发，不能继续远离电机端运行")
            return
        if self.upper_active is False:
            reply = QMessageBox.question(
                self,
                "上限位未触发",
                "当前未检测到上限位触发。仍然开始远离电机端拍摄吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        default_name = datetime.now().strftime("scan_%Y%m%d_%H%M%S")
        file_name, ok = QInputDialog.getText(
            self, "保存文件名", "请输入文件名（不含扩展名）:", QLineEdit.Normal, default_name
        )
        if not ok or not file_name.strip():
            self.log("未输入文件名，取消拍摄")
            return

        self.current_file_name = self.sanitize_file_name(file_name.strip())
        self.synthesizer = ImageSynthesizer()
        self.finishing_capture = False
        self.returning_home = False
        self.manual_motion_mode = None
        self.active_motion_direction = None

        if not self.apply_params():
            QMessageBox.warning(self, "参数错误", "参数设置失败，请检查日志")
            return

        try:
            if not self.camera_thread.start_grabbing():
                self.log("相机开始取流失败，取消运动")
                return

            self.is_capturing = True
            self.motor_running = True
            self.active_motion_direction = self.DIRECTION_FAR_MOTOR
            self.capture_start_time = time.monotonic()
            self.update_control_states()
            self.log(f"开始联动拍摄: {self.current_file_name}.bmp")
            self.log("相机已开始取流，发送远离电机端运动指令")
            if not self.start_p_motion(
                self.DIRECTION_FAR_MOTOR, self.motor_freq_spin.value(), self.max_pulses_spin.value()
            ):
                self.finish_capture(save_image=False, reason="电机启动失败", send_stop=True)
        except Exception as exc:
            self.log(f"开始联动拍摄异常: {exc}")
            traceback.print_exc()
            self.finish_capture(save_image=False, reason="启动异常", send_stop=True)

    def manual_stop(self):
        if self.is_capturing:
            self.finish_capture(save_image=True, reason="手动停止", send_stop=True)
            return
        self.manual_motion_mode = None
        self.returning_home = False
        self.motor_running = False
        self.active_motion_direction = None
        self.send_command("S")
        self.set_motor_status("已发送停止指令")
        self.update_control_states()

    def finish_capture(self, save_image, reason, send_stop):
        if self.finishing_capture:
            return
        if not self.is_capturing and not self.motor_running:
            if send_stop:
                self.send_command("S")
            return

        self.finishing_capture = True
        self.log(f"停止联动: {reason}")
        if send_stop:
            self.send_command("S")

        try:
            if self.camera_thread is not None:
                self.camera_thread.stop_grabbing()
        finally:
            self.is_capturing = False
            self.motor_running = False
            self.active_motion_direction = None
            self.update_control_states()

        if save_image:
            self.start_image_save(reason)
            self.start_return_home()
        else:
            self.log("本次未保存图像")

        self.finishing_capture = False
        if not self.returning_home:
            self.query_motor_status()

    def start_return_home(self):
        if not self.serial_port or not self.serial_port.is_open:
            self.log("串口未连接，无法自动回到上限位")
            return
        if self.upper_active:
            self.returning_home = False
            self.motor_running = False
            self.active_motion_direction = None
            self.set_motor_status("已在上限位，等待下一次拍摄")
            self.log("当前已触发上限位，无需回上限位运动")
            self.update_control_states()
            return
        direction = self.DIRECTION_NEAR_MOTOR
        self.manual_motion_mode = None
        self.returning_home = True
        self.motor_running = True
        self.active_motion_direction = direction
        self.set_motor_status("回上限位：靠近电机端")
        self.update_control_states()
        home_frequency = self.home_return_freq
        self.log(
            f"模组开始回到上限位，方向 D{direction}（靠近电机端），"
            f"固定频率 {home_frequency} Hz，最大脉冲 {self.max_pulses_spin.value()}"
        )
        if not self.start_p_motion(direction, home_frequency, self.max_pulses_spin.value()):
            self.returning_home = False
            self.motor_running = False
            self.active_motion_direction = None
            self.set_motor_status("回上限位启动失败")
            self.update_control_states()

    def manual_return_home(self):
        if not self.serial_port or not self.serial_port.is_open:
            QMessageBox.warning(self, "无法回上限位", "请先连接 Arduino")
            return
        if self.upper_active:
            QMessageBox.information(self, "无需回上限位", "当前上限位已触发")
            return
        if self.is_capturing or self.motor_running or self.returning_home:
            self.log("设备正在运动，不能启动回上限位")
            return
        self.start_return_home()

    def apply_debug_motor_params(self, query_status=True, direction=None):
        if not self.serial_port or not self.serial_port.is_open:
            self.log("串口未连接，无法应用调试参数")
            return False
        if self.is_capturing or self.motor_running:
            self.log("设备正在运动，不能修改调试参数")
            return False

        if direction is None:
            direction = self.debug_dir_combo.currentData()
        ok = self.send_motion_params(direction, self.debug_freq_spin.value())
        if query_status:
            self.query_motor_status()
        return ok

    def debug_move_down(self):
        if not self.serial_port or not self.serial_port.is_open:
            self.log("串口未连接，无法远离电机端运动")
            return
        if self.is_capturing or self.motor_running:
            self.log("设备正在运动，无法启动远离电机端运动")
            return
        if self.lower_active:
            QMessageBox.warning(self, "无法远离电机端", "当前下限位已触发")
            return
        direction = self.DIRECTION_FAR_MOTOR
        self.returning_home = False
        self.manual_motion_mode = "DOWN"
        self.motor_running = True
        self.active_motion_direction = direction
        self.set_motor_status("调试远离电机端运动中")
        self.update_control_states()
        pulses = self.debug_pulses_spin.value()
        self.log(f"调试远离电机端运动，方向 D{direction}，脉冲 {pulses}")
        if not self.start_p_motion(direction, self.debug_freq_spin.value(), pulses):
            self.manual_motion_mode = None
            self.motor_running = False
            self.active_motion_direction = None
            self.set_motor_status("调试远离电机端启动失败")
            self.update_control_states()

    def debug_move_up(self):
        if not self.serial_port or not self.serial_port.is_open:
            self.log("串口未连接，无法靠近电机端运动")
            return
        if self.is_capturing or self.motor_running:
            self.log("设备正在运动，无法启动靠近电机端运动")
            return
        if self.upper_active:
            QMessageBox.information(self, "无需回上限位", "当前上限位已触发")
            return
        direction = self.DIRECTION_NEAR_MOTOR
        pulses = self.debug_pulses_spin.value()
        self.manual_motion_mode = "UP"
        self.returning_home = False
        self.motor_running = True
        self.active_motion_direction = direction
        self.set_motor_status("调试靠近电机端运动中")
        self.update_control_states()
        self.log(f"调试靠近电机端运动，方向 D{direction}，脉冲 {pulses}")
        if not self.start_p_motion(direction, self.debug_freq_spin.value(), pulses):
            self.manual_motion_mode = None
            self.motor_running = False
            self.active_motion_direction = None
            self.set_motor_status("调试靠近电机端启动失败")
            self.update_control_states()

    def debug_jog_selected_dir(self):
        if not self.serial_port or not self.serial_port.is_open:
            self.log("串口未连接，无法点动")
            return
        if self.is_capturing or self.motor_running:
            self.log("设备正在运动，无法启动点动")
            return
        direction = self.debug_dir_combo.currentData()
        self.returning_home = False
        self.manual_motion_mode = "JOG"
        self.motor_running = True
        self.active_motion_direction = direction
        self.set_motor_status(f"按当前方向运动中：{self.direction_name(direction)}")
        self.update_control_states()
        pulses = self.debug_pulses_spin.value()
        self.log(f"按当前方向运动：{self.direction_name(direction)}，方向 D{direction}，脉冲 {pulses}")
        if not self.start_p_motion(direction, self.debug_freq_spin.value(), pulses):
            self.manual_motion_mode = None
            self.motor_running = False
            self.active_motion_direction = None
            self.set_motor_status("按当前方向启动失败")
            self.update_control_states()

    def debug_stop_motor(self):
        self.manual_motion_mode = None
        self.returning_home = False
        self.motor_running = False
        self.active_motion_direction = None
        self.send_command("S")
        self.set_motor_status("已发送停止指令")
        self.update_control_states()

    @staticmethod
    def set_combo_by_data(combo, value):
        if combo.currentData() == value:
            return
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
                return

    def on_frame_received(self, img_array):
        try:
            if self.is_capturing and img_array is not None:
                self.synthesizer.add_frame(img_array)
                frame_count = self.synthesizer.get_frame_count()
                if frame_count % 100 == 0:
                    total_lines = self.synthesizer.get_total_height()
                    elapsed = max(time.monotonic() - self.capture_start_time, 0.001)
                    actual_line_rate = total_lines / elapsed
                    self.log(
                        f"已接收 {frame_count} 帧 = {total_lines} 行，估算行频: {actual_line_rate:.0f} line/s"
                    )
        except Exception as exc:
            self.log(f"接收帧异常: {exc}")
            traceback.print_exc()

    def update_preview(self, img_array):
        try:
            if img_array is None:
                return
            if len(img_array.shape) == 3:
                if img_array.shape[2] == 3:
                    height, width, _ = img_array.shape
                    qimg = QImage(img_array.data, width, height, 3 * width, QImage.Format_RGB888)
                elif img_array.shape[2] == 1:
                    height, width, _ = img_array.shape
                    qimg = QImage(img_array.data, width, height, QImage.Format_Grayscale8)
                else:
                    return
            else:
                height, width = img_array.shape
                qimg = QImage(img_array.data, width, height, QImage.Format_Grayscale8)

            pixmap = QPixmap.fromImage(qimg)
            scaled = pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.preview_label.setPixmap(scaled)
        except Exception as exc:
            self.log(f"预览更新异常: {exc}")
            traceback.print_exc()

    def start_image_save(self, reason):
        try:
            frames = list(getattr(self.synthesizer, "frames", []))
            if not frames:
                self.log("没有接收到图像数据，未保存")
                return

            frame_count = self.synthesizer.get_frame_count()
            total_height = self.synthesizer.get_total_height()
            self.refresh_default_save_dir()
            thread = ImageSaveThread(
                frames,
                self.current_file_name,
                self.save_dir,
                reason,
                self.capture_start_time,
                frame_count,
                total_height,
            )
            thread.saved.connect(self.on_image_saved)
            thread.no_data.connect(lambda: self.log("没有接收到图像数据，未保存"))
            thread.error.connect(self.on_image_save_error)
            thread.finished.connect(lambda t=thread: self.forget_save_thread(t))
            self.save_threads.append(thread)
            self.log(f"正在后台保存图像到: {self.save_dir}")
            thread.start()
        except Exception as exc:
            self.log(f"启动图像保存失败: {exc}")
            traceback.print_exc()

    def on_image_saved(self, full_path, frame_count, total_height, width, actual_line_rate, reason):
        self.log(f"图像已保存: {full_path}")
        self.log(
            f"停止原因: {reason}; 合成信息: {frame_count} 帧 = {total_height} 行, "
            f"尺寸 {width} x {total_height}, 估算行频 {actual_line_rate:.0f} line/s"
        )
        self.info_label.setText(
            f"已保存: {os.path.basename(full_path)}\n"
            f"尺寸: {width} x {total_height}\n"
            f"停止原因: {reason}\n"
            f"估算行频: {actual_line_rate:.0f} line/s"
        )

    def on_image_save_error(self, message):
        self.log(message)

    def forget_save_thread(self, thread):
        if thread in self.save_threads:
            self.save_threads.remove(thread)

    def update_control_states(self):
        serial_ready = self.serial_port is not None and self.serial_port.is_open
        camera_ready = self.camera_thread is not None
        busy = self.is_capturing or self.motor_running or self.returning_home
        debug_busy = self.is_capturing or self.motor_running

        self.start_btn.setEnabled(serial_ready and camera_ready and not busy)
        self.stop_btn.setEnabled(serial_ready and busy)
        self.home_btn.setEnabled(serial_ready and not busy)
        self.init_cam_btn.setEnabled(not busy)
        self.apply_params_btn.setEnabled(not busy)
        for button in self.connect_buttons:
            button.setEnabled(not busy)
        for button in self.refresh_buttons:
            button.setEnabled(not busy)
        for combo in self.port_combos:
            combo.setEnabled(not busy and not serial_ready)
        for combo in self.baud_combos:
            combo.setEnabled(not busy and not serial_ready)
        self.line_frequency_input.setEnabled(not busy)
        self.motor_freq_spin.setEnabled(not busy)
        self.accel_spin.setEnabled(not busy)
        self.decel_spin.setEnabled(not busy)
        self.max_pulses_spin.setEnabled(not busy)
        self.down_dir_combo.setEnabled(not busy)
        self.debug_freq_spin.setEnabled(not debug_busy)
        self.debug_pulses_spin.setEnabled(not debug_busy)
        self.debug_dir_combo.setEnabled(not debug_busy)
        self.apply_debug_params_btn.setEnabled(serial_ready and not debug_busy)
        self.debug_move_down_btn.setEnabled(serial_ready and not debug_busy and not self.lower_active)
        self.debug_move_up_btn.setEnabled(serial_ready and not debug_busy and not self.upper_active)
        selected_debug_dir = self.debug_dir_combo.currentData() if hasattr(self, "debug_dir_combo") else None
        jog_blocked = bool(self.is_direction_blocked_by_limit(selected_debug_dir)) if selected_debug_dir is not None else False
        self.debug_jog_dir_btn.setEnabled(serial_ready and not debug_busy and not jog_blocked)
        self.debug_stop_btn.setEnabled(serial_ready and (self.motor_running or self.returning_home))

    @staticmethod
    def sanitize_file_name(name):
        cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
        return cleaned or datetime.now().strftime("scan_%Y%m%d_%H%M%S")

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        try:
            if self.is_capturing or self.motor_running:
                self.send_command("S")
            self.status_timer.stop()
            if self.camera_thread is not None:
                self.camera_thread.cleanup()
                self.camera_thread = None
            if self.serial_thread is not None:
                self.serial_thread.stop()
                self.serial_thread = None
            for thread in list(self.save_threads):
                if thread.isRunning():
                    thread.wait()
            if self.serial_port is not None and self.serial_port.is_open:
                self.serial_port.close()
        except Exception as exc:
            self.log(f"关闭程序异常: {exc}")
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = IntegratedWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
