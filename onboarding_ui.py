"""Optional first-run guide; no network requests or implicit device permission."""
from zoneinfo import available_timezones
from PySide6.QtCore import QTimeZone,Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QCheckBox
from ui_components import label,btn
from ui_theme import STYLE
import desktop_store as store
import preferences_service as preferences


def system_timezone():
    return bytes(QTimeZone.systemTimeZoneId()).decode('utf-8') or 'UTC'


class WelcomeDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.saved=False
        self.setObjectName('welcomeDialog');self.setWindowTitle('Добро пожаловать в Орбиту')
        self.setAttribute(Qt.WA_DeleteOnClose);self.setWindowModality(Qt.WindowModal)
        self.setStyleSheet(STYLE+'QDialog {background:#1c273c;}')
        self.resize(590,min(540,self.screen().availableGeometry().height()-60))
        box=QVBoxLayout(self);box.setContentsMargins(24,24,24,24);box.setSpacing(14)
        box.addWidget(label('Добро пожаловать в Орбиту',23,'#c3f5e5',True))
        note=label('Здесь можно создавать напоминания, вести проекты, получать отчёты и учиться. Начальный профиль пустой; шаблоны автоматизаций выключены до настройки.',14)
        note.setWordWrap(True);box.addWidget(note)
        box.addWidget(label('Часовой пояс · определён по настройкам устройства',12))
        self.zone=QComboBox();self.zone.setObjectName('welcomeTimezone');self.zone.setEditable(True)
        self.zone.addItems(sorted(available_timezones()));self.zone.setCurrentText(store.timezone_name());box.addWidget(self.zone)
        self.toasts=QCheckBox('Показывать всплывающие уведомления');self.toasts.setChecked(store.get_setting('toasts',True));box.addWidget(self.toasts)
        self.motion=QCheckBox('Анимировать погоду');self.motion.setChecked(store.get_setting('animations',True));box.addWidget(self.motion)
        privacy=label('Данные хранятся в профиле текущего пользователя. Погода необязательна: город можно выбрать позже. Доступ к геолокации запрашивается только после нажатия соответствующей кнопки.',12)
        privacy.setWordWrap(True);box.addWidget(privacy)
        self.error=label('',12,'#ffb8b8');self.error.setWordWrap(True);box.addWidget(self.error);box.addStretch()
        actions=QHBoxLayout();start=btn('Начать',self.accept,True);start.setObjectName('finishWelcome');actions.addWidget(start)
        weather=btn('Настроить погоду',self.open_weather);weather.setObjectName('welcomeWeather');actions.addWidget(weather);box.addLayout(actions)

    def save(self):
        if self.saved:return True
        try:preferences.complete(self.zone.currentText(),self.toasts.isChecked(),self.motion.isChecked())
        except Exception as exc:self.error.setText('Настройки не сохранены: '+str(exc));return False
        self.saved=True;self.owner.tick();return True

    def accept(self):
        if self.save():super().accept()

    def reject(self):
        if self.save():super().reject()

    def closeEvent(self,event):
        if self.save():super().closeEvent(event)
        else:event.ignore()

    def open_weather(self):
        if self.save():
            super().accept();self.owner.configure_location()
