"""Reusable desktop views; never imported by the application core."""
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QColor,QPainter,QPen,QLinearGradient
from PySide6.QtWidgets import QLabel,QPushButton,QFrame,QWidget,QGridLayout,QDialog


def label(text,size=13,color='#a9b6cd',bold=False):
    widget=QLabel(text);widget.setTextFormat(Qt.PlainText)
    widget.setStyleSheet(f'color:{color};font-size:{size}px;font-weight:{600 if bold else 400};')
    return widget


def btn(text,callback,primary=False):
    widget=QPushButton(text);widget.setCursor(Qt.PointingHandCursor)
    widget.setProperty('primary',primary);widget.clicked.connect(callback);return widget


class GlassCard(QFrame):
    def __init__(self,tint='#354c63',parent=None):
        super().__init__(parent);self.tint=tint;self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        if self.isWindow():
            p.setCompositionMode(QPainter.CompositionMode_Source);p.fillRect(self.rect(),Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        rect=QRectF(self.rect()).adjusted(1,1,-1,-1)
        gradient=QLinearGradient(0,0,self.width(),self.height())
        color=QColor(self.tint);color.setAlpha(248 if self.isWindow() else 135)
        gradient.setColorAt(0,color);gradient.setColorAt(1,QColor(25,34,54,248 if self.isWindow() else 185))
        p.setBrush(gradient);p.setPen(QPen(QColor(224,239,255,42),1));p.drawRoundedRect(rect,22,22)


class NavigationBar(QWidget):
    def __init__(self,titles,callback):
        super().__init__();self.columns=0;self.buttons=[]
        self.box=QGridLayout(self);self.box.setContentsMargins(0,0,0,0);self.box.setSpacing(8)
        for index,title in enumerate(titles):
            item=btn(title,lambda checked=False,i=index:callback(i));item.setProperty('navigation',True);self.buttons.append(item)
        self.arrange(3)

    def arrange(self,columns):
        if self.columns==columns:return
        self.columns=columns
        for item in self.buttons:self.box.removeWidget(item)
        for index,item in enumerate(self.buttons):self.box.addWidget(item,index//columns,index%columns)
        for index in range(len(self.buttons)):self.box.setColumnStretch(index,1 if index<columns else 0)

    def resizeEvent(self,event):
        columns=(6 if self.width()>=680 else 3) if len(self.buttons)==6 else (5 if self.width()>=600 else 3)
        self.arrange(columns);super().resizeEvent(event)


class SaveGuardDialog(QDialog):
    """Escape follows the same persistence contract as the close button."""
    def reject(self):
        if self.flush():super().reject()
