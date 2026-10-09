import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QFileDialog,
                             QTextEdit, QProgressBar)
from PyQt5.QtCore import Qt


class FileComparator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.folder1_path = ""
        self.folder2_path = ""
        self.initUI()

    def initUI(self):
        self.setWindowTitle('文件夹文件比对工具')
        self.setGeometry(100, 100, 800, 600)

        # 创建主窗口部件
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        # 创建主布局
        layout = QVBoxLayout()

        # 文件夹选择区域
        folder_layout = QHBoxLayout()

        # 第一个文件夹选择
        self.folder1_label = QLabel('文件夹1: 未选择')
        self.folder1_label.setStyleSheet("QLabel { padding: 5px; }")
        self.folder1_btn = QPushButton('选择文件夹1')
        self.folder1_btn.clicked.connect(lambda: self.select_folder(1))

        # 第二个文件夹选择
        self.folder2_label = QLabel('文件夹2: 未选择')
        self.folder2_label.setStyleSheet("QLabel { padding: 5px; }")
        self.folder2_btn = QPushButton('选择文件夹2')
        self.folder2_btn.clicked.connect(lambda: self.select_folder(2))

        # 添加到布局
        folder_layout.addWidget(self.folder1_btn)
        folder_layout.addWidget(self.folder1_label, 1)
        folder_layout.addWidget(self.folder2_btn)
        folder_layout.addWidget(self.folder2_label, 1)

        # 开始比对按钮
        self.compare_btn = QPushButton('开始比对')
        self.compare_btn.clicked.connect(self.compare_folders)
        self.compare_btn.setEnabled(False)
        self.compare_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 10px;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)

        # 结果显示区域
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setStyleSheet("""
            QTextEdit {
                background-color: #f9f9f9;
                border: 2px solid #ddd;
                border-radius: 4px;
                padding: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)

        # 统计标签
        self.stats_label = QLabel('准备就绪')
        self.stats_label.setStyleSheet("QLabel { color: #666; padding: 5px; }")

        # 添加到主布局
        layout.addLayout(folder_layout)
        layout.addWidget(self.compare_btn)
        layout.addWidget(self.result_text)
        layout.addWidget(self.stats_label)

        main_widget.setLayout(layout)

        # 设置样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f0f0;
            }
            QPushButton {
                padding: 8px 16px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f5f5f5;
            }
            QLabel {
                font-size: 14px;
            }
        """)

    def select_folder(self, folder_num):
        """选择文件夹"""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            f'选择文件夹{folder_num}',
            os.path.expanduser("~")
        )

        if folder_path:
            if folder_num == 1:
                self.folder1_path = folder_path
                self.folder1_label.setText(f'文件夹1: {folder_path}')
            else:
                self.folder2_path = folder_path
                self.folder2_label.setText(f'文件夹2: {folder_path}')

            # 检查是否可以启用比对按钮
            self.check_compare_enabled()

    def check_compare_enabled(self):
        """检查是否可以启用比对按钮"""
        if self.folder1_path and self.folder2_path:
            self.compare_btn.setEnabled(True)
        else:
            self.compare_btn.setEnabled(False)

    def compare_folders(self):
        """比对两个文件夹的文件"""
        if not self.folder1_path or not self.folder2_path:
            self.result_text.setText("请先选择两个文件夹！")
            return

        try:
            # 获取文件夹中的文件列表
            files1 = set(os.listdir(self.folder1_path))
            files2 = set(os.listdir(self.folder2_path))

            # 只保留文件，排除文件夹
            files1 = {f for f in files1 if os.path.isfile(os.path.join(self.folder1_path, f))}
            files2 = {f for f in files2 if os.path.isfile(os.path.join(self.folder2_path, f))}

            # 找出不匹配的文件
            only_in_folder1 = files1 - files2
            only_in_folder2 = files2 - files1

            # 显示结果
            result = []
            result.append("=== 比对结果 ===\n")

            if only_in_folder1:
                result.append(f"仅在文件夹1中找到的文件 ({len(only_in_folder1)}个):")
                for file in sorted(only_in_folder1):
                    result.append(f"  - {file}")
                result.append("")

            if only_in_folder2:
                result.append(f"仅在文件夹2中找到的文件 ({len(only_in_folder2)}个):")
                for file in sorted(only_in_folder2):
                    result.append(f"  - {file}")
                result.append("")

            if not only_in_folder1 and not only_in_folder2:
                result.append("✅ 两个文件夹中的文件名完全匹配！")
            else:
                result.append(f"📊 统计:")
                result.append(f"  文件夹1总文件数: {len(files1)}")
                result.append(f"  文件夹2总文件数: {len(files2)}")
                result.append(f"  不匹配文件数: {len(only_in_folder1) + len(only_in_folder2)}")

            # 更新界面
            self.result_text.setText("\n".join(result))

            # 更新统计标签
            if not only_in_folder1 and not only_in_folder2:
                self.stats_label.setText("✅ 比对完成：文件名完全匹配")
                self.stats_label.setStyleSheet("QLabel { color: #4CAF50; padding: 5px; }")
            else:
                self.stats_label.setText(
                    f"⚠️ 比对完成：发现 {len(only_in_folder1) + len(only_in_folder2)} 个不匹配的文件")
                self.stats_label.setStyleSheet("QLabel { color: #ff9800; padding: 5px; }")

        except Exception as e:
            self.result_text.setText(f"❌ 比对过程中出现错误：\n{str(e)}")
            self.stats_label.setText("❌ 比对失败")
            self.stats_label.setStyleSheet("QLabel { color: #f44336; padding: 5px; }")


def main():
    app = QApplication(sys.argv)

    # 设置应用程序样式
    app.setStyle('Fusion')

    # 创建并显示主窗口
    comparator = FileComparator()
    comparator.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()