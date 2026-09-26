"""
Qt Compatibility Abstraction Module
Provides seamless support for PySide6 and PyQt5, including QtMultimedia widgets.
"""
import sys

try:
    from PySide6 import QtCore, QtWidgets, QtGui
    from PySide6.QtCore import Qt, Signal, Slot, QThread, QUrl, QMimeData, QTimer, QFileSystemWatcher
    from PySide6.QtGui import QAction, QKeySequence, QDesktopServices, QShortcut
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QFileDialog, QTableWidget, QTableWidgetItem, 
        QHeaderView, QTextEdit, QLineEdit, QAbstractItemView, QProgressBar, 
        QComboBox, QMessageBox, QGroupBox, QSplitter, QDoubleSpinBox, QSlider,
        QCheckBox, QRadioButton, QSpinBox, QTabWidget, QGraphicsView, QGraphicsScene, QScrollArea,
        QInputDialog, QScrollBar, QColorDialog, QMenu, QToolButton, QStyledItemDelegate,
        QStyleOptionViewItem, QDialog, QDialogButtonBox
    )
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
    from PySide6.QtMultimediaWidgets import QVideoWidget
    IS_PYSIDE6 = True

    def create_media_content(url):
        return url

except ImportError:
    from PyQt5 import QtCore, QtWidgets, QtGui
    from PyQt5.QtCore import Qt, pyqtSignal as Signal, pyqtSlot as Slot, QThread, QUrl, QMimeData, QTimer, QFileSystemWatcher
    from PyQt5.QtGui import QKeySequence, QDesktopServices
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QFileDialog, QTableWidget, QTableWidgetItem, 
        QHeaderView, QTextEdit, QLineEdit, QAbstractItemView, QProgressBar, 
        QComboBox, QMessageBox, QGroupBox, QSplitter, QDoubleSpinBox, QSlider,
        QCheckBox, QRadioButton, QSpinBox, QTabWidget, QGraphicsView, QGraphicsScene, QScrollArea,
        QInputDialog, QScrollBar, QColorDialog, QMenu, QAction, QToolButton, QStyledItemDelegate,
        QStyleOptionViewItem, QDialog, QDialogButtonBox, QShortcut
    )
    from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
    from PyQt5.QtMultimediaWidgets import QVideoWidget
    IS_PYSIDE6 = False

    class QAudioOutput:
        def __init__(self, parent=None): pass
        def setVolume(self, v): pass
        def setMuted(self, m): pass
        def setDevice(self, d): pass

    class QMediaDevices:
        @staticmethod
        def defaultAudioOutput():
            return None

    def create_media_content(url):
        return QMediaContent(url)
