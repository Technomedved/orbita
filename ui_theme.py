"""Shared glass palette and vector-drawn controls, without external image assets."""
from PySide6.QtCore import Qt,QRectF,QPointF
from PySide6.QtGui import QColor,QPainter,QPainterPath,QPen
from PySide6.QtWidgets import QProxyStyle,QStyle,QStyleFactory

STYLE='''
QWidget {color:#edf2ff;font-family:'Segoe UI';font-size:13px;}
QLabel {background:transparent;}
QPushButton {background:rgba(255,255,255,15);border:1px solid rgba(255,255,255,26);
 border-radius:13px;padding:9px 14px;color:#dce5fa;}
QPushButton:hover {background:rgba(170,200,255,38);border-color:rgba(188,214,255,100);}
QPushButton:pressed {background:rgba(170,200,255,65);}
QPushButton:focus {border-color:#93d9cb;}
QPushButton:disabled {color:#72819b;border-color:rgba(255,255,255,12);}
QPushButton[primary="true"] {color:#14232a;background:#a3eed8;border-color:#c1ffed;font-weight:600;}
QPushButton[primary="true"]:hover {background:#c1ffed;}
QPushButton[primary="true"]:pressed {background:#86d6bf;}
QPushButton[primary="true"]:disabled {color:#7e9a99;background:#2b454b;border-color:#415d64;}
QPushButton[active="true"] {color:#c9f8eb;background:rgba(110,231,195,28);border-color:rgba(145,239,213,85);}
QPushButton[navigation="true"] {padding:9px 10px;font-size:12px;}
QPushButton[windowControl="true"] {border-radius:11px;padding:0;background:rgba(255,255,255,9);}
QPushButton[closeControl="true"]:hover {background:rgba(247,119,132,42);border-color:#c77c8e;color:#ffe0e6;}
QScrollArea,QScrollArea > QWidget > QWidget {background:transparent;border:none;}
QScrollBar:vertical {background:transparent;width:7px;margin:8px 0;}
QScrollBar::handle:vertical {background:#4a526b;border-radius:3px;min-height:30px;}
QScrollBar::handle:vertical:hover {background:#71829c;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0px;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QCheckBox {spacing:12px;padding:8px 0;}
QTextBrowser {background:rgba(255,255,255,10);border:1px solid #3d4861;border-radius:16px;padding:14px;}
QToolTip {color:#edf2ff;background:#29334a;border:1px solid #68768e;padding:6px;}
QLineEdit,QTextEdit,QPlainTextEdit,QComboBox,QSpinBox,QDoubleSpinBox,QDateTimeEdit,QTimeEdit {
 background:#26344b;border:1px solid #4a5872;border-radius:10px;padding:8px;
 selection-background-color:#477d79;selection-color:#f6fffb;}
QLineEdit:focus,QTextEdit:focus,QPlainTextEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus,QDateTimeEdit:focus,QTimeEdit:focus {
 border-color:#90d6c5;}
QLineEdit:disabled,QComboBox:disabled,QSpinBox:disabled,QDoubleSpinBox:disabled,QDateTimeEdit:disabled,QTimeEdit:disabled {color:#7e8ba3;background:#202c40;}
QListWidget {background:rgba(23,35,53,170);border:1px solid #40526c;border-radius:10px;padding:5px;outline:0;}
QListWidget::item {padding:8px;border-radius:6px;}
QListWidget::item:selected {background:#345b61;color:#d2fff0;}
QListWidget::item:hover {background:#30465b;}
QTabWidget::pane {background:rgba(27,40,59,100);border:1px solid #41516b;border-radius:12px;top:-1px;}
QTabBar::tab {background:rgba(255,255,255,12);border:1px solid #41516b;border-bottom:none;border-top-left-radius:10px;border-top-right-radius:10px;padding:9px 14px;margin-right:4px;}
QTabBar::tab:selected {color:#c9f8eb;background:#294650;border-color:#6f9c9a;}
QTabBar::tab:hover {background:#334c60;}
QComboBox {padding-right:32px;min-height:20px;}
QComboBox QAbstractItemView {background:#26344b;border:1px solid #526078;padding:5px;selection-background-color:#435976;outline:0;}
QMenu {background:#243049;border:1px solid #4a5872;padding:6px;}
QMenu::item {padding:8px 20px;border-radius:6px;}
QMenu::item:selected {background:#40536c;}
'''


class GlassStyle(QProxyStyle):
    def pixelMetric(self,metric,option=None,widget=None):
        if metric in (QStyle.PM_IndicatorWidth,QStyle.PM_IndicatorHeight):return 18
        return super().pixelMetric(metric,option,widget)

    def drawPrimitive(self,element,option,painter,widget=None):
        if element in (QStyle.PE_IndicatorArrowDown,QStyle.PE_IndicatorArrowUp,
                       QStyle.PE_IndicatorSpinDown,QStyle.PE_IndicatorSpinUp):
            painter.save();painter.setRenderHint(QPainter.Antialiasing)
            center=QRectF(option.rect).center();direction=1 if element in (QStyle.PE_IndicatorArrowDown,QStyle.PE_IndicatorSpinDown) else -1
            painter.setPen(QPen(QColor('#bfd2e4' if option.state&QStyle.State_Enabled else '#687991'),1.5,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
            path=QPainterPath();path.moveTo(center.x()-3.5,center.y()-direction*1.8)
            path.lineTo(center.x(),center.y()+direction*1.8);path.lineTo(center.x()+3.5,center.y()-direction*1.8)
            painter.drawPath(path);painter.restore();return
        if element!=QStyle.PE_IndicatorCheckBox:
            return super().drawPrimitive(element,option,painter,widget)
        painter.save();painter.setRenderHint(QPainter.Antialiasing)
        rect=QRectF(option.rect).adjusted(1,1,-1,-1)
        enabled=bool(option.state&QStyle.State_Enabled)
        checked=bool(option.state&(QStyle.State_On|QStyle.State_NoChange))
        hovered=bool(option.state&(QStyle.State_MouseOver|QStyle.State_HasFocus))
        painter.setPen(QPen(QColor('#b9f8e7' if checked and enabled else '#86c7b9' if hovered else '#627389'),1.2))
        painter.setBrush(QColor('#a3eed8' if checked and enabled else '#45655f' if checked else '#253449'))
        painter.drawRoundedRect(rect,4,4)
        if checked:
            painter.setPen(QPen(QColor('#15382e' if enabled else '#c4d8d1'),1.9,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
            if option.state&QStyle.State_NoChange:
                painter.drawLine(QPointF(rect.left()+4,rect.center().y()),QPointF(rect.right()-4,rect.center().y()))
            else:
                path=QPainterPath();path.moveTo(rect.left()+3.5,rect.center().y())
                path.lineTo(rect.left()+6.7,rect.bottom()-4);path.lineTo(rect.right()-3,rect.top()+4)
                painter.drawPath(path)
        painter.restore()


def install_theme(app):
    if app.property('orbitaGlassTheme'):return
    app._orbita_style=GlassStyle(QStyleFactory.create('Fusion'))
    app.setStyle(app._orbita_style);app.setStyleSheet(STYLE)
    app.setProperty('orbitaGlassTheme',True)
