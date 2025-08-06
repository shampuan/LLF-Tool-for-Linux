#!/usr/bin/env python3

import sys
import os
import subprocess
import threading
import time
import re
import math 

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QPushButton, QProgressBar, QLabel,
    QMessageBox, QFrame, QMenuBar, QMenu, QAction,
    QSpacerItem, QSizePolicy
)
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtCore import Qt, QTimer, QEvent, QObject, QUrl

# Import multimedia module
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent


# --- Custom Event Classes ---
class ProgressUpdateEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.User + 1)

    def __init__(self, progress, elapsed_time, write_speed, disk_size_bytes, bytes_copied):
        super().__init__(ProgressUpdateEvent.EVENT_TYPE)
        self.progress = progress
        self.elapsed_time = elapsed_time
        self.write_speed = write_speed
        self.disk_size_bytes = disk_size_bytes
        self.bytes_copied = bytes_copied

class MessageEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.User + 2)

    def __init__(self, title, message, icon):
        super().__init__(MessageEvent.EVENT_TYPE)
        self.title = title
        self.message = message
        self.icon = icon

class OperationCompleteEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.User + 3)

    def __init__(self, success, operation_type, error_message=""):
        super().__init__(OperationCompleteEvent.EVENT_TYPE)
        self.success = success
        self.operation_type = operation_type
        self.error_message = error_message


class LLFTool(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LLF Tool Linux")
        
        base_path = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_path, "LLF_Tool.png")
        self.setWindowIcon(QIcon(icon_path))
        
        self.setGeometry(100, 100, 600, 300) 

        self.current_language = "tr"
        self.disk_wipe_thread = None
        self.is_wiping = False
        self.start_time = 0

        self.load_translations()
        self.init_ui()

        # Initialize QMediaPlayer
        self.media_player = QMediaPlayer()
        # DEĞİŞİKLİK BURADA BAŞLIYOR
        mp3_file_path = os.path.join(base_path, "At The Shore_Kevin Macleod.mp3")
        # DEĞİŞİKLİK BURADA BİTİYOR
        self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(mp3_file_path)))
        self.media_player.setVolume(50) # Set default volume to 50%
        # Connect media status changed signal for looping
        self.media_player.mediaStatusChanged.connect(self.on_media_status_changed)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10) 

        self.menu_bar = QMenuBar(self)
        main_layout.addWidget(self.menu_bar)

        about_menu = self.menu_bar.addMenu(self.tr_text("About"))
        about_action = QAction(self.tr_text("About"), self)
        about_action.triggered.connect(self.show_about_dialog)
        about_menu.addAction(about_action)

        language_menu = self.menu_bar.addMenu(self.tr_text("Language"))
        lang_tr_action = QAction("Türkçe", self)
        lang_tr_action.triggered.connect(lambda: self.set_language("tr"))
        language_menu.addAction(lang_tr_action)
        lang_en_action = QAction("English", self)
        lang_en_action.triggered.connect(lambda: self.set_language("en"))
        language_menu.addAction(lang_en_action)

        # Add "Ses" menu and "Ses Çal" action
        audio_menu = self.menu_bar.addMenu(self.tr_text("Ses"))
        self.play_audio_action = QAction(self.tr_text("Ses Çal"), self)
        self.play_audio_action.setCheckable(True)
        self.play_audio_action.setChecked(True) # Default to checked
        audio_menu.addAction(self.play_audio_action)


        main_layout.addSpacing(5) 

        disk_selection_layout = QHBoxLayout()
        self.select_disk_label = QLabel(self.tr_text("Select Disk:"))
        disk_selection_layout.addWidget(self.select_disk_label)
        self.disk_combo = QComboBox()
        self.populate_disk_combo()
        disk_selection_layout.addWidget(self.disk_combo, 1)
        main_layout.addLayout(disk_selection_layout)

        main_layout.addSpacing(10) 

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        main_layout.addSpacing(15) 

        bottom_section_layout = QHBoxLayout()

        emblem_container_layout = QVBoxLayout()
        emblem_container_layout.setContentsMargins(0,0,0,0) 
        emblem_container_layout.setSpacing(0) 

        base_path = os.path.dirname(os.path.abspath(__file__))
        emblem_path = os.path.join(base_path, "LLF_Tool.png")
        self.emblem_label = QLabel()
        self.emblem_label.setFixedSize(120, 120)
        self.emblem_label.setPixmap(QPixmap(emblem_path).scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)) 

        emblem_container_layout.addWidget(self.emblem_label, alignment=Qt.AlignCenter) 
        bottom_section_layout.addLayout(emblem_container_layout)
        
        bottom_section_layout.addSpacerItem(QSpacerItem(20, 0, QSizePolicy.Fixed, QSizePolicy.Minimum))

        status_text_layout = QVBoxLayout()
        status_text_layout.setContentsMargins(0,0,0,0) 
        status_text_layout.setSpacing(0) 

        self.write_speed_label = QLabel(self.tr_text("Yazma hızı: ....MB/s"))
        self.estimated_time_label = QLabel(self.tr_text("Tahmini kalan süre:"))
        self.elapsed_time_label = QLabel(self.tr_text("Toplam geçen süre:"))

        self.write_speed_label.setStyleSheet("padding: 0px;")
        self.estimated_time_label.setStyleSheet("padding: 0px;")
        self.elapsed_time_label.setStyleSheet("padding: 0px;")

        status_text_layout.addWidget(self.write_speed_label)
        status_text_layout.addWidget(self.estimated_time_label)
        status_text_layout.addWidget(self.elapsed_time_label)
        status_text_layout.addStretch(1) 

        bottom_section_layout.addLayout(status_text_layout, 1)

        button_layout = QVBoxLayout()
        button_layout.addStretch(1) 

        self.full_format_button = QPushButton(self.tr_text("FormatButton"))
        self.full_format_button.setFixedSize(150, 30)
        self.full_format_button.clicked.connect(self.confirm_and_start_full_format)
        button_layout.addWidget(self.full_format_button, alignment=Qt.AlignRight)

        self.delete_mbr_mft_button = QPushButton(self.tr_text("Delete Only MBR-MFT"))
        self.delete_mbr_mft_button.setFixedSize(150, 30)
        self.delete_mbr_mft_button.clicked.connect(self.confirm_and_start_mbr_mft_delete)
        button_layout.addWidget(self.delete_mbr_mft_button, alignment=Qt.AlignRight)
        
        bottom_section_layout.addLayout(button_layout)
        main_layout.addLayout(bottom_section_layout)

        main_layout.addStretch(1) 

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_status)
        self.timer.start(1000)

    def setMenuBar(self, menubar):
        self.layout().insertWidget(0, menubar)

    def populate_disk_combo(self):
        self.disk_combo.clear()
        try:
            result = subprocess.run(['lsblk', '-bnd', '-o', 'NAME,SIZE,TYPE,MODEL'], capture_output=True, text=True, check=True)
            lines = result.stdout.strip().split('\n')

            if not lines or (len(lines) == 1 and not lines[0]):
                self.disk_combo.addItem(self.tr_text("Diskler bulunamadı"))
                return

            for line in lines:
                parts = line.split()
                if len(parts) >= 3: 
                    name = parts[0].strip()
                    size_bytes_str = parts[1].strip()
                    disk_type = parts[2].strip()

                    if disk_type != "disk": 
                        continue

                    try:
                        size_bytes = int(size_bytes_str)
                    except ValueError:
                        print(f"Uyarı: Disk boyutu parse edilemedi, atlanıyor: '{size_bytes_str}'")
                        continue

                    model = " ".join(parts[3:]).strip() if len(parts) > 3 else self.tr_text("Bilinmiyor")

                    is_usb = False
                    if "usb" in model.lower() or "flash" in model.lower():
                        is_usb = True
                    
                    size_gb = size_bytes / (1024**3)
                    size_label = f"{size_gb:.2f} GB"

                    usb_label = self.tr_text(" (USB)") if is_usb else ""

                    display_text = f"/dev/{name} - {size_label} - {model}{usb_label}"
                    self.disk_combo.addItem(display_text, userData=f"/dev/{name}")
        except FileNotFoundError:
            QApplication.instance().postEvent(self, MessageEvent(self.tr_text("Hata"), self.tr_text("`lsblk` komutu bulunamadı. Lütfen yüklü olduğundan emin olun (genellikle util-linux paketiyle gelir)."), QMessageBox.Critical))
            self.disk_combo.addItem(self.tr_text("Diskler yüklenemedi"))
        except subprocess.CalledProcessError as e:
            QApplication.instance().postEvent(self, MessageEvent(self.tr_text("Hata"), self.tr_text(f"Diskler listelenirken bir hata oluştu: {e.stderr}"), QMessageBox.Critical))
            self.disk_combo.addItem(self.tr_text("Diskler yüklenemedi"))
        except Exception as e:
            QApplication.instance().postEvent(self, MessageEvent(self.tr_text("Hata"), self.tr_text(f"Beklenmeyen bir hata oluştu: {e}"), QMessageBox.Critical))
            self.disk_combo.addItem(self.tr_text("Diskler yüklenemedi"))


    def load_translations(self):
        self.translations = {
            "tr": {
                "LLF Tool Linux": "LLF Tool Linux", 
                "About": "Hakkında",
                "Language": "Dil",
                "Ses": "Ses", 
                "Ses Çal": "Ses Çal", 
                "Select Disk:": "Disk Seç:",
                "Yazma hızı: ....MB/s": "Yazma hızı: ....MB/s",
                "Tahmini kalan süre:": "Tahmini kalan süre:",
                "Toplam geçen süre:": "Toplam geçen süre:",
                "FormatButton": "Formatla",
                "Delete Only MBR&MFT": "Sadece MBR ve MFT Sil",
                "Diskler yüklenemedi": "Diskler yüklenemedi",
                "Diskler bulunamadı": "Diskler bulunamadı",
                "Bilinmiyor": "Bilinmiyor",
                " (USB)": " (USB)",
                "Hata": "Hata",
                "`lsblk` komutu bulunamadı. Lütfen yüklü olduğundan emin olun (genellikle util-linux paketiyle gelir).": "`lsblk` komutu bulunamadı. Lütfen yüklü olduğundan emin olun (genellikle util-linux paketiyle gelir).",
                "Diskler listelenirken bir hata oluştu: ": "Diskler listelenirken bir hata oluştu: ",
                "Beklenmeyen bir hata oluştu: ": "Beklenmeyen bir hata oluştu: ",
                "Uyarı": "Uyarı",
                "Seçilen disk": "Seçilen disk",
                "Diski doğru seçtiğinizden emin misiniz? Bu işlem geri alınamaz!": "Diski doğru seçtiğinizden emin misiniz? Bu işlem geri alınamaz! Bu, tüm verilerinizi kalıcı olarak silecektir.",
                "İşlem Başlatılıyor...": "İşlem Başlatılıyor...",
                "Seçili disk bulunamadı veya geçersiz.": "Seçili disk bulunamadı veya geçersiz.",
                "Uyarı!": "Uyarı!",
                "Devam etmek istiyor musunuz?": "Devam etmek istiyor musunuz?",
                "İşlem tamamlandı!": "İşlem tamamlandı!",
                "Diski tamamen silme işlemi tamamlandı.": "Diski tamamen silme işlemi tamamlandı.",
                "MBR/MFT silme işlemi tamamlandı.": "MBR/MFT silme işlemi tamamlandı.",
                "Diski silme işlemi sırasında bir hata oluştu: ": "Diski silme işlemi sırasında bir hata oluştu: ",
                "Sadece MBR/MFT silme işlemi sırasında bir hata oluştu: ": "Sadece MBR/MFT silme işlemi sırasında bir hata oluştu: ",
                "`dd` veya `pkexec` komutu bulunamadı. Lütfen yüklü olduklarından emin olun.": "`dd` veya `pkexec` komutu bulunamadı. Lütfen yüklü olduklarından emin olun.",
                "Komut hatası: ": "Komut hatası: ",
                "Uygulama Bilgisi": "Uygulama Bilgisi",
                "Bu araç, Debian tabanlı Linux sistemleri için basit bir Düşük Seviyeli Format (LLF) aracıdır.": "LLF Tool Linux\nVersiyon: 1.0\nLisans: GNU GPLv3\nGeliştirici: A. Serhat KILIÇOĞLU - github.com/shampuan\n\nDisklere Low Level Format atmak için geliştirilmiş bir mini araç.",
                "İşlem zaten devam ediyor.": "İşlem zaten devam ediyor.",
                "İşlem İptal Edildi": "İşlem İptal Edildi",
                "Yazma hızı:": "Yazma hızı:",
                "Tahmini kalan süre:": "Tahmini kalan süre:",
                "Toplam geçen süre:": "Toplam geçen süre:",
                "Disk doldu. İşlem başarıyla tamamlandı.": "Disk doldu. İşlem başarıyla tamamlandı.", # Yeni çeviri
                "Disk doldu ancak dd bir hata bildirdi. İşlem başarılı olabilir.": "Disk doldu ancak dd bir hata bildirdi. İşlem başarılı olabilir." # Yeni çeviri
            },
            "en": {
                "LLF Tool Linux": "LLF Tool Linux", 
                "About": "About",
                "Language": "Language",
                "Ses": "Audio", 
                "Ses Çal": "Play Audio", 
                "Select Disk:": "Select Disk:",
                "Yazma hızı: ....MB/s": "Write speed: ....MB/s",
                "Tahmini kalan süre:": "Estimated remaining time:",
                "Toplam geçen süre:": "Total elapsed time:",
                "FormatButton": "Format",
                "Delete Only MBR&MFT": "Delete Only MBR & MFT",
                "Diskler yüklenemedi": "Disks could not be loaded",
                "Diskler bulunamadı": "No disks found",
                "Bilinmiyor": "Unknown",
                " (USB)": " (USB)",
                "Hata": "Error",
                "`lsblk` komutu bulunamadı. Lütfen yüklü olduğundan emin olun (genellikle util-linux paketiyle gelir).": "`lsblk` command not found. Please ensure it's installed (usually comes with util-linux package).",
                "Diskler listelenirken bir hata oluştu: ": "An error occurred while listing disks: ",
                "Beklenmeyen bir hata oluştu: ": "An unexpected error occurred: ",
                "Uyarı": "Warning",
                "Seçilen disk": "Selected Disk",
                "Diski doğru seçtiğinizden emin misiniz? Bu işlem geri alınamaz!": "Are you sure you have selected the correct disk? This operation is irreversible! It will permanently erase all your data.",
                "İşlem Başlatılıyor...": "Operation Starting...",
                "Seçili disk bulunamadı veya geçersiz.": "Selected disk not found or invalid.",
                "Uyarı!": "Warning!",
                "Devam etmek istiyor musunuz?": "Do you want to continue?",
                "İşlem tamamlandı!": "Operation completed!",
                "Diski tamamen silme işlemi tamamlandı.": "Full disk wipe operation completed.",
                "MBR/MFT silme işlemi tamamlandı.": "MBR/MFT deletion operation completed.",
                "Diski silme işlemi sırasında bir hata oluştu: ": "An error occurred during disk wipe: ",
                "Sadece MBR/MFT silme işlemi sırasında bir hata oluştu: ": "An error occurred during MBR/MFT deletion: ",
                "`dd` veya `pkexec` komutu bulunamadı. Lütfen yüklü olduklarından emin olun.": "`dd` or `pkexec` command not found. Please ensure they are installed.",
                "Komut hatası: ": "Command error: ",
                "Uygulama Bilgisi": "Application Information",
                "Bu araç, Debian tabanlı Linux sistemleri için basit bir Düşük Seviyeli Format (LLF) aracıdır.": "LLF Tool Linux\nVersion: 1.0\nLicense: GNU GPLv3\nDeveloper: A. Serhat KILIÇOĞLU - github.com/shampuan\n\nA mini tool developed for performing Low Level Format on disks.",
                "İşlem zaten devam ediyor.": "Operation is already in progress.",
                "İşlem İptal Edildi": "Operation Canceled",
                "Yazma hızı:": "Write speed:",
                "Tahmini kalan süre:": "Estimated remaining time:",
                "Toplam geçen süre:": "Total elapsed time:",
                "Disk doldu. İşlem başarıyla tamamlandı.": "Disk full. Operation completed successfully.", # Yeni çeviri
                "Disk doldu ancak dd bir hata bildirdi. İşlem başarılı olabilir.": "Disk full but dd reported an error. Operation might be successful." # Yeni çeviri
            }
        }

    def tr_text(self, key):
        return self.translations[self.current_language].get(key, key)

    def set_language(self, lang):
        self.current_language = lang
        self.update_ui_texts()

    def update_ui_texts(self):
        self.setWindowTitle(self.tr_text("LLF Tool Linux")) 

        self.menu_bar.clear()
        about_menu = self.menu_bar.addMenu(self.tr_text("About"))
        about_action = QAction(self.tr_text("About"), self)
        about_action.triggered.connect(self.show_about_dialog)
        about_menu.addAction(about_action)

        language_menu = self.menu_bar.addMenu(self.tr_text("Language"))
        lang_tr_action = QAction("Türkçe", self)
        lang_tr_action.triggered.connect(lambda: self.set_language("tr"))
        language_menu.addAction(lang_tr_action)
        lang_en_action = QAction("English", self)
        lang_en_action.triggered.connect(lambda: self.set_language("en"))
        language_menu.addAction(lang_en_action)

        # Update "Ses" menu and "Ses Çal" action text
        audio_menu = self.menu_bar.addMenu(self.tr_text("Ses"))
        self.play_audio_action = QAction(self.tr_text("Ses Çal"), self)
        self.play_audio_action.setCheckable(True)
        self.play_audio_action.setChecked(True) # Ensure it remains checked if it was
        audio_menu.addAction(self.play_audio_action)


        self.select_disk_label.setText(self.tr_text("Select Disk:"))
        self.write_speed_label.setText(self.tr_text("Yazma hızı: ....MB/s"))
        self.estimated_time_label.setText(self.tr_text("Tahmini kalan süre:"))
        self.elapsed_time_label.setText(self.tr_text("Toplam geçen süre:"))
        self.full_format_button.setText(self.tr_text("FormatButton"))
        self.delete_mbr_mft_button.setText(self.tr_text("Delete Only MBR&MFT"))

        current_disk_path = self.disk_combo.currentData()
        self.populate_disk_combo()
        if current_disk_path:
            index = self.disk_combo.findData(current_disk_path)
            if index != -1:
                self.disk_combo.setCurrentIndex(index)


    def show_about_dialog(self):
        QMessageBox.information(self, self.tr_text("Uygulama Bilgisi"), self.tr_text("Bu araç, Debian tabanlı Linux sistemleri için basit bir Düşük Seviyeli Format (LLF) aracıdır."))

    def confirm_and_start_full_format(self):
        if self.is_wiping:
            QMessageBox.warning(self, self.tr_text("Uyarı"), self.tr_text("İşlem zaten devam ediyor."))
            return

        selected_disk_path = self.disk_combo.currentData()
        if not selected_disk_path or not selected_disk_path.startswith("/dev/"):
            QMessageBox.critical(self, self.tr_text("Hata"), self.tr_text("Seçili disk bulunamadı veya geçersiz."))
            return

        # Start audio playback if "Ses Çal" is checked (only for full format)
        if self.play_audio_action.isChecked():
            if self.media_player.state() != QMediaPlayer.PlayingState:
                self.media_player.play()

        reply = QMessageBox.warning(
            self,
            self.tr_text("Uyarı"),
            f"{self.tr_text('Seçilen disk')}: {selected_disk_path}\n\n{self.tr_text('Diski doğru seçtiğinizden emin misiniz? Bu işlem geri alınamaz!')}\n\n{self.tr_text('Devam etmek istiyor musunuz?')}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.start_wipe_operation(selected_disk_path, "full_format")
        else:
            QMessageBox.information(self, self.tr_text("İşlem İptal Edildi"), self.tr_text("İşlem İptal Edildi"))
            self.media_player.stop() # Stop audio if operation is cancelled


    def confirm_and_start_mbr_mft_delete(self):
        if self.is_wiping:
            QMessageBox.warning(self, self.tr_text("Uyarı"), self.tr_text("İşlem zaten devam ediyor."))
            return

        selected_disk_path = self.disk_combo.currentData()
        if not selected_disk_path or not selected_disk_path.startswith("/dev/"):
            QMessageBox.critical(self, self.tr_text("Hata"), self.tr_text("Seçili disk bulunamadı veya geçersiz."))
            return

        # Audio playback is intentionally NOT started for MBR/MFT delete

        reply = QMessageBox.warning(
            self,
            self.tr_text("Uyarı"),
            f"{self.tr_text('Seçilen disk')}: {selected_disk_path}\n\n{self.tr_text('Diski doğru seçtiğinizdan emin misiniz? Bu işlem geri alınamaz!')}\n\n{self.tr_text('Devam etmek istiyor musunuz?')}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.start_wipe_operation(selected_disk_path, "mbr_mft_delete")
        else:
            QMessageBox.information(self, self.tr_text("İşlem İptal Edildi"), self.tr_text("İşlem İptal Edildi"))
            # If the music was somehow playing (e.g., from a previous full format action), stop it.
            self.media_player.stop()


    def start_wipe_operation(self, disk_path, operation_type):
        self.is_wiping = True
        self.progress_bar.setValue(0)
        self.start_time = time.time()
        self.write_speed_label.setText(self.tr_text("Yazma hızı: ....MB/s"))
        self.estimated_time_label.setText(self.tr_text("Tahmini kalan süre:"))
        self.elapsed_time_label.setText(self.tr_text("Toplam geçen süre:"))
        self.set_buttons_enabled(False)

        self.disk_wipe_thread = threading.Thread(target=self.perform_wipe, args=(disk_path, operation_type))
        self.disk_wipe_thread.daemon = True
        self.disk_wipe_thread.start()

    def set_buttons_enabled(self, enabled):
        self.full_format_button.setEnabled(enabled)
        self.delete_mbr_mft_button.setEnabled(enabled)
        self.disk_combo.setEnabled(enabled)


    def perform_wipe(self, disk_path, operation_type):
        try:
            disk_size_bytes = 0 
            dd_bs_in_bytes = 4 * 1024 * 1024 # 4MB in bytes

            if operation_type == "full_format":
                result = subprocess.run(['lsblk', '-bno', 'SIZE', disk_path], capture_output=True, text=True, check=True)
                disk_size_bytes_str = result.stdout.strip().split('\n')[0]
                disk_size_bytes = int(disk_size_bytes_str)

                total_blocks = math.ceil(disk_size_bytes / dd_bs_in_bytes)
                
                command = ['pkexec', 'dd', 'if=/dev/zero', f'of={disk_path}', 
                           f'bs={dd_bs_in_bytes}', f'count={total_blocks}', 'status=progress', 'oflag=sync'] 
                
                process = subprocess.Popen(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                
                while True:
                    line = process.stderr.readline() 
                    if not line and process.poll() is not None:
                        break 

                    if line:
                        match = re.search(r'(\d+)\s*(?:bytes|bayt)\s*\(.*?\)\s*(?:copied|kopyalandı),\s*([\d.]+)\s*s(?:,\s*([\d.,]+\s*[KMGT]?B/s))?', line)
                        if match:
                            try:
                                bytes_copied = int(match.group(1))
                                elapsed_time = float(match.group(2))
                                write_speed_str = match.group(3) if match.group(3) else self.tr_text("Bilinmiyor")
                                
                                progress = (bytes_copied / disk_size_bytes) * 100 if disk_size_bytes > 0 else 0
                                QApplication.instance().postEvent(self, ProgressUpdateEvent(progress, elapsed_time, write_speed_str, disk_size_bytes, bytes_copied))
                            except (ValueError, TypeError) as e:
                                print(f"Hata: dd çıktısı parse edilemedi: {e}, Satır: '{line.strip()}'")
                    time.sleep(0.01)

                stdout_output, stderr_output = process.communicate()
                
                if process.returncode != 0:
                    full_error_message = f"Dönüş kodu: {process.returncode}"
                    if stderr_output:
                        full_error_message += f"\nStderr: {stderr_output.strip()}"
                    if stdout_output:
                        full_error_message += f"\nStdout: {stdout_output.strip()}"
                    
                    # Dd'nin disk dolduğunda döndürdüğü hata mesajlarını kontrol et
                    # İngilizce ve Türkçe varyasyonları kontrol edelim
                    disk_full_messages = [
                        "No space left on device",  # Common English error
                        "disk doldu",               # Common Turkish error (dd'nin Türkçeleştirilmiş çıktısı)
                        "Yazma sırasında hata: Cihazda yer kalmadı", # Another possible Turkish error
                        "Error writing: No space left on device" # Another common English error
                    ]
                    
                    is_disk_full_error = any(msg.lower() in stderr_output.lower() for msg in disk_full_messages)

                    if is_disk_full_error:
                        # Eğer disk doldu hatası ise, işlemi başarılı say
                        QApplication.instance().postEvent(self, OperationCompleteEvent(True, operation_type, self.tr_text("Disk doldu. İşlem başarıyla tamamlandı.")))
                    else:
                        # Gerçek bir hata ise, hatayı bildir
                        QApplication.instance().postEvent(self, OperationCompleteEvent(False, operation_type, full_error_message))
                else:
                    QApplication.instance().postEvent(self, OperationCompleteEvent(True, operation_type))


            elif operation_type == "mbr_mft_delete":
                command = ['pkexec', 'dd', 'if=/dev/zero', f'of={disk_path}', 'bs=4M', 'count=1', 'oflag=sync']
                
                process = subprocess.Popen(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                
                stdout_output, stderr_output = process.communicate()
                
                if process.returncode == 0:
                    QApplication.instance().postEvent(self, OperationCompleteEvent(True, operation_type))
                else:
                    full_error_message = f"Dönüş kodu: {process.returncode}"
                    if stderr_output:
                        full_error_message += f"\nStderr: {stderr_output.strip()}"
                    if stdout_output:
                        full_error_message += f"\nStdout: {stdout_output.strip()}"
                    QApplication.instance().postEvent(self, OperationCompleteEvent(False, operation_type, full_error_message))


        except FileNotFoundError:
            QApplication.instance().postEvent(self, MessageEvent(self.tr_text("Hata"), self.tr_text("`dd` veya `pkexec` komutu bulunamadı. Lütfen yüklü olduklarından emin olun."), QMessageBox.Critical))
            QApplication.instance().postEvent(self, OperationCompleteEvent(False, operation_type, self.tr_text("Komut bulunamadı.")))
        except subprocess.CalledProcessError as e:
            QApplication.instance().postEvent(self, MessageEvent(self.tr_text("Hata"), self.tr_text(f"Komut hatası: {e.stderr.strip()}"), QMessageBox.Critical))
            QApplication.instance().postEvent(self, OperationCompleteEvent(False, operation_type, e.stderr.strip()))
        except Exception as e:
            QApplication.instance().postEvent(self, MessageEvent(self.tr_text("Hata"), self.tr_text(f"Beklenmeyen bir hata oluştu: {e}"), QMessageBox.Critical))
            QApplication.instance().postEvent(self, OperationCompleteEvent(False, operation_type, str(e)))

    def on_media_status_changed(self, status):
        # If media playback has ended and the "Play Audio" option is checked and an operation is ongoing,
        # restart the media.
        # Ensure looping only if it's a full format operation (self.is_wiping will be true only if an operation starts)
        # And the play_audio_action is checked.
        if status == QMediaPlayer.EndOfMedia and self.play_audio_action.isChecked() and self.is_wiping:
            self.media_player.play()

    def update_status(self):
        if not self.is_wiping:
            self.write_speed_label.setText(self.tr_text("Yazma hızı: ....MB/s"))
            self.estimated_time_label.setText(self.tr_text("Tahmini kalan süre:"))
            self.elapsed_time_label.setText(self.tr_text("Toplam geçen süre:"))

    def customEvent(self, event):
        if event.type() == ProgressUpdateEvent.EVENT_TYPE:
            self.progress_bar.setValue(int(event.progress))
            self.elapsed_time_label.setText(f"{self.tr_text('Toplam geçen süre:')} {self.format_time(event.elapsed_time)}")
            self.write_speed_label.setText(f"{self.tr_text('Yazma hızı:')} {event.write_speed}")

            if event.bytes_copied > 0 and event.elapsed_time > 0 and event.disk_size_bytes > 0:
                remaining_bytes = event.disk_size_bytes - event.bytes_copied
                bytes_per_second = event.bytes_copied / event.elapsed_time
                if bytes_per_second > 0:
                    estimated_remaining_seconds = remaining_bytes / bytes_per_second
                    self.estimated_time_label.setText(f"{self.tr_text('Tahmini kalan süre:')} {self.format_time(estimated_remaining_seconds)}")

        elif event.type() == MessageEvent.EVENT_TYPE:
            QMessageBox(event.icon, event.title, event.message, QMessageBox.Ok, self).exec_()

        elif event.type() == OperationCompleteEvent.EVENT_TYPE:
            self.is_wiping = False
            self.set_buttons_enabled(True)
            self.media_player.stop() # Stop audio when operation completes or fails
            
            if event.success: 
                self.progress_bar.setValue(100)
            else: 
                pass 

            if event.success:
                message = event.error_message if event.error_message else (self.tr_text("Diski tamamen silme işlemi tamamlandı.") if event.operation_type == "full_format" else self.tr_text("MBR/MFT silme işlemi tamamlandı."))
                QMessageBox.information(self, self.tr_text("İşlem tamamlandı!"), message)
            else:
                message = self.tr_text("Diski silme işlemi sırasında bir hata oluştu: ") + event.error_message if event.operation_type == "full_format" else self.tr_text("Sadece MBR/MFT silme işlemi sırasında bir hata oluştu: ") + event.error_message
                QMessageBox.critical(self, self.tr_text("Hata"), message)


    def format_time(self, seconds):
        if seconds is None:
            return "N/A"
        seconds = int(seconds)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LLFTool()
    window.show()
    sys.exit(app.exec_())
