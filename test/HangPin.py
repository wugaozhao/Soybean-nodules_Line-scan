import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QComboBox,
    QPushButton, QVBoxLayout, QFormLayout, QGroupBox, QMessageBox,
    QSizePolicy
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

class LineScanCalculator(QWidget):
    def __init__(self):
        super().__init__()
        # 固定参数
        self.lead_l = 5.0          # 丝杆导程 mm
        self.pixel_p = 21.0        # 像元尺寸 μm
        self.full_steps = 200      # 电机每圈步数 (1.8°)
        self.beta = 1.0            # 放大倍率 β=1
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("线扫相机行频计算")
        self.setMinimumSize(560, 520)
        self.resize(580, 540)

        # 设置更大的全局基础字体
        font = QFont()
        font.setPointSize(11)
        self.setFont(font)

        self.setStyleSheet("""
            QWidget {
                font-size: 15px;
                font-family: "Microsoft YaHei", "Segoe UI";
            }
            QGroupBox {
                font-weight: bold;
                font-size: 15px;
                border: 1px solid #b0b0b0;
                border-radius: 10px;
                margin-top: 14px;
                padding-top: 20px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 18px;
                padding: 0 8px;
            }
            QLineEdit {
                padding: 10px;
                border: 1px solid #b0b0b0;
                border-radius: 6px;
                background: white;
                font-size: 15px;
                min-height: 24px;
            }
            QComboBox {
                padding: 10px;
                border: 1px solid #b0b0b0;
                border-radius: 6px;
                background: white;
                font-size: 15px;
                min-height: 24px;
            }
            QPushButton {
                background: #4f6ef7;
                color: white;
                border: none;
                padding: 14px;
                border-radius: 10px;
                font-weight: bold;
                font-size: 17px;
                min-height: 28px;
            }
            QPushButton:hover {
                background: #3b54e0;
            }
            QPushButton:pressed {
                background: #2c44c0;
            }
            QLabel {
                font-size: 15px;
                min-height: 24px;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(24, 20, 24, 20)

        # 固定参数显示
        param_group = QGroupBox("系统固定参数")
        param_layout = QFormLayout()
        param_layout.setSpacing(14)
        param_layout.setContentsMargins(14, 14, 14, 14)

        param_layout.addRow(self._make_label("丝杆导程 L："), self._make_value_label("5 mm"))
        param_layout.addRow(self._make_label("像元尺寸 p："), self._make_value_label("21 μm"))
        param_layout.addRow(self._make_label("电机步距角："), self._make_value_label("1.8° (200步/转)"))
        param_layout.addRow(self._make_label("光学放大倍率 β："), self._make_value_label("1 (1:1)"))
        param_group.setLayout(param_layout)
        main_layout.addWidget(param_group)

        # 输入区域
        input_group = QGroupBox("输入参数")
        input_layout = QFormLayout()
        input_layout.setSpacing(14)
        input_layout.setContentsMargins(14, 14, 14, 14)

        self.pulse_freq_edit = QLineEdit()
        self.pulse_freq_edit.setPlaceholderText("例如 10000")
        self.pulse_freq_edit.setMinimumHeight(36)
        input_layout.addRow(self._make_label("脉冲频率 (Hz)："), self.pulse_freq_edit)

        self.microstep_combo = QComboBox()
        microsteps = ["1", "2", "4", "8", "16", "32", "64", "128", "256"]
        self.microstep_combo.addItems(microsteps)
        self.microstep_combo.setCurrentIndex(3)  # 默认8
        self.microstep_combo.setMinimumHeight(36)
        input_layout.addRow(self._make_label("细分数："), self.microstep_combo)

        input_group.setLayout(input_layout)
        main_layout.addWidget(input_group)

        # 计算按钮
        self.calc_btn = QPushButton("计算行频")
        self.calc_btn.clicked.connect(self.calculate)
        self.calc_btn.setMinimumHeight(46)
        main_layout.addWidget(self.calc_btn)

        # 结果显示
        result_group = QGroupBox("计算结果")
        result_layout = QVBoxLayout()
        result_layout.setContentsMargins(14, 16, 14, 16)
        result_layout.setSpacing(12)

        self.result_label = QLabel("-- Hz")
        self.result_label.setAlignment(Qt.AlignCenter)
        res_font = QFont()
        res_font.setPointSize(24)
        res_font.setBold(True)
        self.result_label.setFont(res_font)
        self.result_label.setStyleSheet("color: #1a202c; padding: 10px;")
        self.result_label.setWordWrap(True)
        self.result_label.setMinimumHeight(60)

        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #5a6c7d; font-size: 13px; padding: 6px;")
        self.info_label.setMinimumHeight(40)

        result_layout.addWidget(self.result_label)
        result_layout.addWidget(self.info_label)
        result_group.setLayout(result_layout)
        main_layout.addWidget(result_group)

        # 底部弹簧，使之上对齐
        main_layout.addStretch(1)

    def _make_label(self, text):
        """创建标准表单标签，保证足够高度"""
        lbl = QLabel(text)
        lbl.setMinimumHeight(30)
        return lbl

    def _make_value_label(self, text):
        """创建固定参数的值标签"""
        lbl = QLabel(text)
        lbl.setMinimumHeight(30)
        return lbl

    def calculate(self):
        pulse_text = self.pulse_freq_edit.text().strip()
        if not pulse_text:
            QMessageBox.warning(self, "输入错误", "请输入脉冲频率")
            return
        try:
            pulse_freq = float(pulse_text)
            if pulse_freq < 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "输入错误", "脉冲频率必须是非负数字")
            return

        microstep = int(self.microstep_combo.currentText())

        N = self.full_steps * microstep
        d_pulse = self.lead_l / N
        d_pix = self.pixel_p * self.beta / 1000.0

        line_freq = pulse_freq * (d_pulse / d_pix)

        self.result_label.setText(f"{line_freq:.2f} Hz")
        info = (
            f"脉冲频率 {pulse_freq} Hz × (导程 {self.lead_l} mm / (200 × {microstep})) "
            f"÷ (像元 {self.pixel_p} μm) = {line_freq:.2f} Hz"
        )
        self.info_label.setText(info)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LineScanCalculator()
    window.show()
    sys.exit(app.exec_())