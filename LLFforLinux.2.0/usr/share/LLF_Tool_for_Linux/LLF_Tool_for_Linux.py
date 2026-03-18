#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import subprocess
import re
import signal
import json
import webbrowser

# Ortam değişkenleri Qt yüklenmeden önce tanımlanmalı
# Bunları gnome ve wayland ortamında sorun çıkmaması açısından koymam şart.
# Dönüp tekrar bakarım. 
os.environ["QT_QPA_PLATFORM"] = "xcb"
os.environ["QT_QPA_PLATFORMTHEME"] = "gtk3"

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, 
    QHeaderView, QTabWidget, QTextEdit, QProgressBar, 
    QCheckBox, QFrame, QStackedWidget, QDialog, QMessageBox,
    QAbstractItemView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QFont, QColor

class FormatConfirmDialog(QDialog):
    def __init__(self, device_path, device_model, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Device Format")
        self.setFixedWidth(450)
        layout = QVBoxLayout(self)

        warning_text = (
    f"You are about to perform a Low Level Format on the following device:<br><br>"
    f"<b>Device:</b> {device_path}<br>"
    f"<b>Model:</b> {device_model}<br><br>"
    "Once you start the process, the disk will be filled with zeros from beginning to end, "
    "and all data will be <b>irreversibly erased</b> (data recovery software will not work). "
    "Therefore, it is <b>STRONGLY RECOMMENDED</b> to ensure you have selected the correct disk "
    "and understand what you are doing!<br><br>"
    "<b>Note:</b> The process may take a long time depending on your disk size.<br>"
    "It is normal for the disk to appear as 'uninitialized' or 'unformatted' once finished.<br>"
    "You will need to create a new partition table and format it to use it again."
)
        
        label = QLabel(warning_text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label)

        layout.addSpacing(10)
        # kullanıcıya uyanık olmasını sağlayalım ve riskleri kabul ettirelim. 
        self.confirm_cb = QCheckBox("I am sure I selected the correct disk and I know what I am doing.\n"
                                    "I am responsible for any potential issues.")
        
        layout.addWidget(self.confirm_cb)

        layout.addSpacing(20)
        # kutucuğu doldurmadan başlayamaz. aşağıda lambda checked ile hallettik.
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Process")
        self.start_btn.setEnabled(False) # Başlangıçta pasif
        self.start_btn.setFixedWidth(120)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(100)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.start_btn)
        layout.addLayout(btn_layout)

        # Checkbox durumuna göre butonu aktif et
        self.confirm_cb.toggled.connect(lambda checked: self.start_btn.setEnabled(checked))
        self.start_btn.clicked.connect(self.accept)
    
class FormatWorker(QThread):
    progress_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal(bool, str)
    log_signal = pyqtSignal(str)

    def __init__(self, device_path, quick_wipe=False):
        super().__init__()
        self.device_path = device_path
        self.quick_wipe = quick_wipe
        self._is_running = True

    def stop(self):
        self._is_running = False
        if hasattr(self, 'process'):
            
            # Bura biraz hassas. İşlem duracaksa tam durmalı. 
            try:
                # Sadece süreci değil, ona bağlı alt süreçleri de durdurur
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            except:
                pass

    def run(self):       
        # 1. DOĞRUDAN YAZMA (Direct I/O): İşletim sisteminin 'yazıldı' deyip 
        # yalan söylemesini engellemek için -d (direct) ekliyoruz.
        # Bu, hızı düşürür ama gerçek zamanlı takibi sağlar.
        try:
            if self.quick_wipe:
                # İlk 10MB'ye ziro fill yapıyoruz.
                cmd = ["ddrescue", "--force", "-v", "--synchronous", "--size=10M", "/dev/zero", self.device_path]
            else:
                size_cmd = ["blockdev", "--getsize64", self.device_path] 
                dev_size = subprocess.check_output(size_cmd).decode().strip()
                cmd = ["ddrescue", "--force", "-v", "--synchronous", f"--size={dev_size}", "/dev/zero", self.device_path]
        except:
            # bu işlem de ddrescue ile yapılmalı. dd iyi değil. 
            cmd = ["ddrescue", "--force", "-v", "--synchronous", "/dev/zero", self.device_path]

        try:
            self.process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                bufsize=1,
                universal_newlines=True,
                preexec_fn=os.setsid # Process grubunu ayırıyoruz (Durdurabilmek için şart)
            )

            for line in self.process.stdout:
                if not self._is_running:
                    try:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    except:
                        pass
                    self.finished_signal.emit(False, "Process stopped by user.")
                    return
                
                self.log_signal.emit(line.strip())
                
                # Regex takibi (Daha kararlı)
                pos_match = re.search(r"(?:ipos|opos):\s+([\d\.]+\s+\w+)", line)
                rate_match = re.search(r"(?:average|current) rate:\s+([\d\.]+\s+\w+/s)", line)
                pct_match = re.search(r"pct\s+(?:rescued|done):\s+([\d\.]+)", line)

                stats = {}
                if pos_match: stats['pos'] = pos_match.group(1)
                if rate_match: stats['rate'] = rate_match.group(1)
                if pct_match: stats['pct'] = float(pct_match.group(1))
                
                if stats:
                    self.progress_signal.emit(stats)

            self.process.wait()

            # 2. SYNC ÇÖZÜMÜ: ddrescue bitse bile işletim sistemine 
            # 'tamponu boşalt ve fiziksel yazmayı bitir' emri veriyoruz.
            self.log_signal.emit("Finalizing: Flushing write buffers (sync)...")
            subprocess.run(["sync"])

            if self.process.returncode == 0:
                self.finished_signal.emit(True, "Format completed successfully.")
            else:
                self.finished_signal.emit(False, f"Error Code: {self.process.returncode}")

        except Exception as e:
            self.finished_signal.emit(False, str(e))

class LLFToolSkeleton(QWidget):
    
    def __init__(self):
        super().__init__()
        # İkon yolunu dinamik olarak belirle
        script_dir = os.path.dirname(os.path.abspath(__file__)) # <--Nerde olursa olsun yanıbaşında arayacak artık. 
        self.icon_path = os.path.join(script_dir, "LLF_Tool.png")
        self.setWindowTitle("LLF Tool for Linux 2.0")
        self.resize(720, 520)
        self.setWindowIcon(QIcon(self.icon_path))
        
        
        # Set global font to Liberation Sans/ms fontlarından kaçınıyoruz.
        self.app_font = QFont("Liberation Sans", 10)
        self.setFont(self.app_font)
        
        self.init_ui()
        self.worker = None
        self.refresh_device_list()
    
    def handle_continue_button(self):
        selected_row = self.device_table.currentRow()
        if selected_row == -1:
            QMessageBox.warning(self, "Warning", "Please select a device from the list first.")
            return
        
        # Sistem diski koruması - program kendi sistemini uçurmasın
        device_path = self.device_table.item(selected_row, 0).data(Qt.ItemDataRole.UserRole)
        if self.is_system_device(device_path):
            QMessageBox.critical(self, "Access Denied", 
                f"The device {device_path} is currently being used by the system (Root or Boot partition).\n\n"
                "Formatting the system drive is NOT allowed for safety reasons.")
            return
        
        # Seçili satırdaki bilgileri al
        model = self.device_table.item(selected_row, 1).text()
        rev = self.device_table.item(selected_row, 2).text()
        size = self.device_table.item(selected_row, 5).text()
        
        info_text = f"{model}  {rev}  [{size}]"
        self.top_device_label.setText(info_text)
        self.bottom_info_label.setText(info_text)
        # Log ekranını temizle ve seçili cihaz bilgisini ekle
        log_content = f"THIS DEVICE SELECTED: {model} [{size}]<br><br>READY TO FORMAT..."
        self.log_output.setHtml(log_content)
        # SMART verilerini yükle
        device_path = self.device_table.item(selected_row, 0).data(Qt.ItemDataRole.UserRole)
        self.update_device_details(device_path)
        
        self.main_stack.setCurrentIndex(1)
        
    def update_device_details(self, device_path):
        
        try:
            # -i ile bilgileri çekiyoruz
            cmd = ["smartctl", "-i", device_path]
            
            env = os.environ.copy()
            # pkexec diyaloğunun GUI'de çıkması için DISPLAY ve XAUTHORITY gerekebilir
            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if result.returncode == 0:
                self.details_text.setPlainText(result.stdout)
            else:
                # USB uyarısını buraya da ekleyelim
                is_usb = subprocess.check_output(["lsblk", "-no", "TRAN", device_path], text=True).strip().lower() == "usb"
                if is_usb:
                    msg = ("S.M.A.R.T does not work for devices connected via USB. "
                           "Therefore, you cannot view detailed information about the selected device.")
                else:
                    msg = f"Device details could not be retrieved.\n\nSystem Message:\n{result.stderr}"
                self.details_text.setPlainText(msg)
        except Exception as e:
            self.details_text.setPlainText(f"An error occurred: {str(e)}")
        
    def show_about_dialog(self):
        from PyQt6.QtGui import QPixmap
        msg = QDialog(self)
        msg.setWindowTitle("About")
        msg.setFixedWidth(500)
        dialog_layout = QVBoxLayout(msg)

        # Logo Alanı
        logo_label = QLabel()
        pixmap = QPixmap(self.icon_path)
        if not pixmap.isNull():
            # Logo: 128x128
            logo_label.setPixmap(pixmap.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dialog_layout.addWidget(logo_label)

        # Metin Alanı
        about_text = (
            "<div style='text-align: center;'>"
            "<h2>LLF Tool for Linux</h2>"
            "<b>Version:</b> 2.0<br>"
            "<b>License:</b> GNU GPLv3<br>"
            "<b>Developer:</b> A. Serhat KILIÇOĞLU (shampuan)<br>"
            "<b>Github:</b> <span style='color: #0084e9;'>www.github.com/shampuan</span><br><br>"
            "This is an open-source alternative for applying LLF processes to mechanical hard drives "
            "on Debian-based systems, modeled after HDD GURU's famous software.<br><br>"
            "This program comes with ABSOLUTELY NO WARRANTY.<br>"
            "Copyright © 2026 - A. Serhat KILIÇOĞLU"
            "</div>"
        )
        
        content_label = QLabel(about_text)
        content_label.setTextFormat(Qt.TextFormat.RichText)
        content_label.setWordWrap(True)
        content_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dialog_layout.addWidget(content_label)

        # Tamam Butonu
        ok_btn = QPushButton("OK")
        ok_btn.setFixedWidth(100)
        ok_btn.clicked.connect(msg.accept)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addStretch()
        dialog_layout.addLayout(btn_layout)

        msg.exec()
    
    def is_system_device(self, device_path):
        try:
            # lsblk ile cihazın mount pointlerini kontrol et
            output = subprocess.check_output(["lsblk", "-no", "MOUNTPOINT", device_path], text=True)
            mount_points = output.strip().split('\n')
            # Eğer / veya /boot/efi gibi kritik yerlere bağlıysa True döndür
            for mp in mount_points:
                if mp == "/" or mp.startswith("/boot"):
                    return True
            return False
        except:
            return False
    
    def refresh_device_list(self):
        # lsblk komutunu JSON formatında, ihtiyacımız olan sütunlarla çağırıyoruz
        cmd = ["lsblk", "-J", "-b", "-d", "-o", "NAME,MODEL,REV,SERIAL,SIZE,TRAN"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            data = json.loads(result.stdout)
            devices = data.get("blockdevices", [])
            
            self.device_table.setRowCount(len(devices))
            self.status_label.setText(f"Disks found: {len(devices)}")
            
            for row, dev in enumerate(devices):
                # Sütunlar: BUS, MODEL, FIRMWARE, SERIAL NUMBER, LBA (Şimdilik boş), CAPACITY
                path = f"/dev/{dev.get('name', '')}"
                bus = dev.get("tran", "N/A").upper()
                model = dev.get("model", "Unknown")
                rev = dev.get("rev", "")
                serial = dev.get("serial", "N/A")
                size_bytes = int(dev.get("size", 0))
                size_gb = f"{size_bytes / (1000**3):.1f} GB"
                
                self.device_table.setItem(row, 0, QTableWidgetItem(bus))
                # USB bellekler genellikle "usb" olarak döner, daha okunaklı yapalım
                display_bus = bus if bus != "N/A" else "UNKNOWN"
                self.device_table.setItem(row, 0, QTableWidgetItem(display_bus))
                # Sistem diski mi kontrol et ve ismi ona göre yaz
                is_sys = self.is_system_device(path)
                display_model = f"{model} (SYSTEM)" if is_sys else model
                model_item = QTableWidgetItem(display_model)
                if is_sys:
                    model_item.setForeground(QColor("red")) # <-- Dikkat çekmesi açısından rengi kırmızı yaptım. 
                
                self.device_table.setItem(row, 1, model_item)
                self.device_table.setItem(row, 2, QTableWidgetItem(rev))
                self.device_table.setItem(row, 3, QTableWidgetItem(serial))
                # Bura cillop oldu burayı böyle bırakalım. 
                
                # LBA yerine varsa cihazın tipini (disk/rom) yazabiliriz veya boş bırakabiliriz
                dev_type = dev.get("type", "disk")
                self.device_table.setItem(row, 4, QTableWidgetItem(dev_type.upper()))
                self.device_table.setItem(row, 5, QTableWidgetItem(size_gb))
    
                # Cihaz yolunu (path) gizli veri olarak ilk sütuna saklayalım
                self.device_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, path)
                
        except Exception as e:
            self.status_label.setText(f"Error listing disks: {str(e)}")

    def refresh_smart_data(self, device_path):
        self.smart_table.setRowCount(0)
        
        # SMART verisini çekmeyi dene (Önce NVMe/SATA fark etmeksizin deniyoruz)
        cmd = ["smartctl", "-a", "--json", device_path]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            data = json.loads(result.stdout) if result.stdout else {}
            
            # Veri geldi mi kontrol et
            has_ata = "ata_smart_attributes" in data
            has_nvme = "nvme_smart_health_information_log" in data

            if not (has_ata or has_nvme):
                # Veri gelmediyse şimdi USB kontrolü yapalım
                is_usb = subprocess.check_output(["lsblk", "-no", "TRAN", device_path], text=True).strip().lower() == "usb"
                if is_usb:
                    msg = "S.M.A.R.T. data is often unavailable for USB-connected devices. Your device may not support this over USB."
                else:
                    msg = "S.M.A.R.T. attributes not found or not supported by this device."
                
                self.smart_table.setRowCount(1)
                self.smart_table.setItem(0, 0, QTableWidgetItem(msg))
                return

            data = json.loads(result.stdout)
            attributes = []

            # NVMe ve ATA ayrımı burası önemli
            if "ata_smart_attributes" in data:
                attributes = data["ata_smart_attributes"].get("table", [])
            elif "nvme_smart_health_information_log" in data:
                nvme_data = data["nvme_smart_health_information_log"]
                for key, val in nvme_data.items():
                    # NVMe verilerini tabloya uygun formata getiriyoruz
                    attributes.append({
                        "name": key.replace("_", " ").title(),
                        "value": "N/A",
                        "raw": {"string": str(val)}
                    })

            if not attributes:
                self.smart_table.setRowCount(1)
                self.smart_table.setItem(0, 0, QTableWidgetItem("No SMART capability was found for this device."))
                return

            self.smart_table.setRowCount(len(attributes))
            for row, attr in enumerate(attributes):
                name = str(attr.get("name", "Unknown"))
                # NVMe'de value olmayabilir, bu durumda raw değerini kullanabiliriz
                val_raw = attr.get("value")
                value = str(val_raw) if val_raw is not None else "N/A"
                raw_value = str(attr.get("raw", {}).get("string", "N/A"))
                
                self.smart_table.setItem(row, 0, QTableWidgetItem(name))
                self.smart_table.setItem(row, 1, QTableWidgetItem(value))
                self.smart_table.setItem(row, 2, QTableWidgetItem(raw_value))
                
        except Exception as e:
            self.smart_table.setRowCount(1)
            self.smart_table.setItem(0, 0, QTableWidgetItem(f"An error occurred.: {str(e)}"))
    
    def init_ui(self):
        # Ana taşıyıcı: İki farklı ekran arasında geçiş yapabilmek için QStackedWidget
        self.main_stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.main_stack)

        # 1. EKRAN: Cihaz Seçimi
        self.device_selection_page = self.create_device_selection_page()
        self.main_stack.addWidget(self.device_selection_page)

        # 2. EKRAN: İşlem Tabları
        self.operation_page = self.create_operation_page()
        self.main_stack.addWidget(self.operation_page)

    def create_device_selection_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        header_layout = QHBoxLayout()
        header = QLabel("LLF TOOL for LINUX 2.0")
        header.setFont(QFont("Liberation Sans", 10))
        link_label = QLabel("www.github.com/shampuan")
        link_label.setStyleSheet("color: #0084e9;") # Hoş bir mavi tutturdum böyle kalsın
        
        
        link_label.setStyleSheet("text-decoration: none; color: #0084e9;")
        
        header_layout.addWidget(header)
        header_layout.addStretch()
        header_layout.addWidget(link_label)
        layout.addLayout(header_layout)

        self.device_info_line = QLabel("Please select a device") # Başlangıçta seçim uyarısı
        self.device_info_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.device_info_line)

        # Cihaz Listesi Tablosu
        self.device_table = QTableWidget(5, 6) 
        self.device_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.device_table.setHorizontalHeaderLabels([
            "BUS", "MODEL", "FIRMWARE", "SERIAL NUMBER", "LBA", "CAPACITY"
        ])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.device_table.horizontalHeader().setStretchLastSection(True)
        
        
        self.device_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.device_table)

        # Red Legal Warning - HDD GURU yapmamıştır falan diyoruz.
        warning_note = QLabel("NOTE: This software is NOT developed by HDD Guru. "
                             "It is an open-source alternative for Debian-based Linux systems.")
        about_link_selection = QLabel("<a href='#'>About</a>")
        about_link_selection.setStyleSheet("text-decoration: none; color: #0084e9;")
        about_link_selection.setStyleSheet("color: #0084e9; text-decoration: underline;")
        about_link_selection.setCursor(Qt.CursorShape.PointingHandCursor)
        about_link_selection.linkActivated.connect(lambda: self.show_about_dialog())
        layout.addWidget(about_link_selection)
        warning_note.setStyleSheet("color: red;")
        layout.addWidget(warning_note)

        # Alt Buton Grubu
        bottom_layout = QHBoxLayout()
        self.status_label = QLabel("Disks found: 0")
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addStretch()
        
        continue_btn = QPushButton("Continue >>>")
        continue_btn.setFixedSize(120, 35)
        continue_btn.clicked.connect(self.handle_continue_button)
        bottom_layout.addWidget(continue_btn)
        
        layout.addLayout(bottom_layout)
        return page

    def create_operation_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        top_info_layout = QHBoxLayout()
        self.top_device_label = QLabel("[0] ST500DM002-1BD142  KC45  [500.1 GB]") # bunlar eskiden kaldı. Böyle kalsın sorun yok. 
        self.top_device_label.setFont(QFont("Liberation Sans", 10, QFont.Weight.Bold))
        
        support_link = QLabel("www.github.com/shampuan")
        support_link.setStyleSheet("color: #0084e9;") 
        
        support_link.setStyleSheet("text-decoration: underline; color: #0084e9;")
        
        support_link.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        top_info_layout.addWidget(self.top_device_label)
        top_info_layout.addStretch()
        top_info_layout.addWidget(support_link)
        layout.addLayout(top_info_layout)

        # Tab Yapısı
        tabs = QTabWidget()
        
        # Sekme 1: Device Details
        details_tab = QWidget()
        det_layout = QVBoxLayout(details_tab)
        self.details_text = QTextEdit("PHYSICAL PARAMETERS:\nLBA mode is supported...")
        self.details_text.setReadOnly(True)
        self.details_text.setFont(QFont("Monospace", 9))
        det_layout.addWidget(self.details_text)
        tabs.addTab(details_tab, "Device details")

        # Sekme 2: LOW-LEVEL FORMAT
        format_tab = QWidget()
        form_layout = QVBoxLayout(format_tab)
        
        self.log_output = QTextEdit()
        self.log_output.setHtml("No device selected.")
        self.log_output.setReadOnly(True)
        # Increase height to push it downwards
        self.log_output.setMinimumHeight(260) 
        form_layout.addWidget(self.log_output)

        # Task Progress Label (Gap closed)
        task_label = QLabel("Current task progress")
        task_label.setFont(QFont("Liberation Sans", 9))
        form_layout.addWidget(task_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(27)
        self.progress_bar.setFont(QFont("Liberation Sans", 10))
        form_layout.addWidget(self.progress_bar)

        # Space between progress and stats
        form_layout.addStretch()

        # Slot System using Grid for Bottom Alignment
        bottom_grid = QGridLayout()
        bottom_grid.setContentsMargins(0, 5, 0, 5)
        bottom_grid.setVerticalSpacing(8)

        # Row 0, Column 0: Percent (Left)
        self.percent_label = QLabel("0% complete")
        self.percent_label.setFont(QFont("Liberation Sans", 11))
        bottom_grid.addWidget(self.percent_label, 0, 0)

        # Row 0, Column 1: Speed (Middle-Right)
        self.speed_label = QLabel("0.0 MB/s")
        # Larger and Bold font for Speed
        self.speed_label.setFont(QFont("Liberation Sans", 12, QFont.Weight.Bold))
        bottom_grid.addWidget(self.speed_label, 0, 1, Qt.AlignmentFlag.AlignCenter)

        # Row 0, Column 2: Quick Wipe (Right)
        self.quick_wipe_cb = QCheckBox("Perform quick wipe (just remove partitions and MBR)")
        bottom_grid.addWidget(self.quick_wipe_cb, 0, 2, Qt.AlignmentFlag.AlignRight)

        # Row 1, Column 0: Sector (Left)
        self.sector_label = QLabel("Current sector:  0")
        self.sector_label.setFont(QFont("Liberation Sans", 11))
        bottom_grid.addWidget(self.sector_label, 1, 0)

        # Row 1, Column 2: Buttons (Right)
        btn_h_layout = QHBoxLayout()
        btn_h_layout.setSpacing(48)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedSize(100, 30)
        self.format_btn = QPushButton("FORMAT THIS DEVICE")
        self.format_btn.clicked.connect(self.handle_format_button)
        self.format_btn.setFixedSize(180, 30)
        self.format_btn.setStyleSheet("font-weight: bold;")
        btn_h_layout.addWidget(self.stop_btn)
        btn_h_layout.addWidget(self.format_btn)
        bottom_grid.addLayout(btn_h_layout, 1, 2, Qt.AlignmentFlag.AlignRight)

        form_layout.addLayout(bottom_grid)
        
        tabs.addTab(format_tab, "LOW-LEVEL FORMAT")

        # Tab 3: S.M.A.R.T.
        smart_tab = QWidget()
        smart_layout = QVBoxLayout(smart_tab)
        
        smart_top_layout = QHBoxLayout()
        smart_info_lbl = QLabel("Select a disk and click the button to retrieve S.M.A.R.T. data.")
        self.get_smart_btn = QPushButton("Get SMART Data")
        self.get_smart_btn.setFixedWidth(150)
        self.get_smart_btn.clicked.connect(self.handle_get_smart_click)
        
        smart_top_layout.addWidget(smart_info_lbl)
        smart_top_layout.addStretch()
        smart_top_layout.addWidget(self.get_smart_btn)
        smart_layout.addLayout(smart_top_layout)

        self.smart_table = QTableWidget(0, 3)
        self.smart_table.setHorizontalHeaderLabels(["ID / Attribute Name", "Normalized Value", "Raw Data"])
        self.smart_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.smart_table.horizontalHeader().setStretchLastSection(True)
        self.smart_table.setColumnWidth(0, 250)
        self.smart_table.setColumnWidth(1, 120)
        self.smart_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.smart_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        smart_layout.addWidget(self.smart_table)
        tabs.addTab(smart_tab, "S.M.A.R.T.")

        layout.addWidget(tabs)

        # Footer Navigation
        

        copyright_layout = QHBoxLayout()
        # "About" linki oluşturuluyor
        about_link = QLabel("<a href='#'>About</a>")
        about_link.setStyleSheet("text-decoration: none; color: #0084e9;")
        about_link.setStyleSheet("color: #0084e9; text-decoration: underline;")
        about_link.setFont(QFont("Liberation Sans", 9))
        about_link.setCursor(Qt.CursorShape.PointingHandCursor)
        about_link.linkActivated.connect(lambda: self.show_about_dialog())
        
        copyright_layout.addWidget(about_link)
        copyright_layout.addStretch()
        layout.addLayout(copyright_layout)
        back_layout = QHBoxLayout()
        self.back_btn = QPushButton("<<< Back to Device Selection")
        self.back_btn.setFixedWidth(220) # Genişliği yazıya uygun bir seviyeye çektik
        self.back_btn.clicked.connect(lambda: self.main_stack.setCurrentIndex(0))
        back_layout.addWidget(self.back_btn)
        back_layout.addStretch() # Butonu sola iten boşluk
        layout.addLayout(back_layout)
        status_info_layout = QHBoxLayout()
        self.version_label = QLabel("LLF Tool for Linux 2.0")
        self.bottom_info_label = QLabel("[0] ST500DM002-1BD142  KC45  [500.1 GB]")
        status_info_layout.addWidget(self.version_label)
        status_info_layout.addStretch()
        status_info_layout.addWidget(self.bottom_info_label)
        layout.addLayout(status_info_layout)

        return page
    
    def handle_format_button(self):
        selected_row = self.device_table.currentRow()
        if selected_row == -1: return

        device_path = self.device_table.item(selected_row, 0).data(Qt.ItemDataRole.UserRole)
        device_model = self.device_table.item(selected_row, 1).text()
        
        dialog = FormatConfirmDialog(device_path, device_model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Arayüz elemanlarını kilitle
            self.format_btn.setEnabled(False)
            self.back_btn.setEnabled(False)
            self.quick_wipe_cb.setEnabled(False)
            self.log_output.clear()
            self.log_output.append(f"<b>Starting LLF process for {device_path}...</b><br>")

            # Worker'ı oluştur ve başlat
            self.worker = FormatWorker(device_path, self.quick_wipe_cb.isChecked())
            self.worker.log_signal.connect(lambda msg: self.log_output.append(msg) if "[A" not in msg else None)
            self.worker.progress_signal.connect(self.update_progress_ui)
            self.worker.finished_signal.connect(self.handle_format_finished)
            
            # Stop butonunu bağla
            try:
                self.stop_btn.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            self.stop_btn.clicked.connect(self.worker.stop)
            
            self.worker.start()

    def update_progress_ui(self, stats):
        if 'pct' in stats:
            self.progress_bar.setValue(int(stats['pct']))
            self.percent_label.setText(f"{stats['pct']}% complete")
        if 'rate' in stats:
            self.speed_label.setText(stats['rate'])
        if 'pos' in stats:
            self.sector_label.setText(f"Current position: {stats['pos']}")

    def handle_format_finished(self, success, message):
        self.format_btn.setEnabled(True)
        self.back_btn.setEnabled(True)
        self.quick_wipe_cb.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.warning(self, "Process Ended", message)

    def handle_get_smart_click(self):
        # İlk sayfadaki tabloda hangi satır seçiliyse onu buluyoruz / bu çok önemli
        selected_row = self.device_table.currentRow()
        if selected_row == -1:
            QMessageBox.warning(self, "Warning", "Please select a device from the list first.")
            return
            
        # Gizli UserRole verisinden seçili diskin yolunu (/dev/sdX gibi) alıyoruz
        device_path = self.device_table.item(selected_row, 0).data(Qt.ItemDataRole.UserRole)
        self.refresh_smart_data(device_path)

if __name__ == "__main__":
    # Root yetkisi yoksa pkexec ile yeniden başlat
    if os.geteuid() != 0:
        display_var = os.environ.get('DISPLAY', ':0')
        xauth_var = os.environ.get('XAUTHORITY', os.path.expanduser('~/.Xauthority'))
        script_path = os.path.abspath(sys.argv[0])
        command = ['pkexec', 'env', f'DISPLAY={display_var}', f'XAUTHORITY={xauth_var}', sys.executable, script_path] + sys.argv[1:]
        try:
            subprocess.run(command, check=True)
            sys.exit(0)
        except Exception:
            sys.exit(1)
    
    # Chromium/QtWebEngine sandbox hatalarını root için devre dışı bırak / TARAYICI OLAYINI İPTAL ETTİK. ARTIK Bİ ANLAMI KALMADI. 
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    os.environ["QT_X11_NO_MITSHM"] = "1" # X11 paylaşımlı bellek hataları için
    
    # Argümanlara sandbox kapama parametrelerini ekle
    sys_args = sys.argv + ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
    
    app = QApplication(sys_args)
    app.setStyle("Fusion")
    window = LLFToolSkeleton()
    window.show()
    sys.exit(app.exec())
