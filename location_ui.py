"""Foreground permission/position adapter and location onboarding dialog."""
import sys
import threading
from zoneinfo import available_timezones
from PySide6.QtCore import QObject,Signal,QTimer,Qt,QLocationPermission,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtPositioning import QGeoPositionInfoSource,QGeoPositionInfo
from PySide6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,
    QListWidget,QListWidgetItem,QFormLayout,QDoubleSpinBox,QSpinBox,QComboBox,QTabWidget,QWidget,QScrollArea,QCheckBox)
from ui_components import label,btn,GlassCard
from ui_theme import STYLE
import desktop_store as store
import location_service as locations


class DeviceLocator(QObject):
    found=Signal(float,float,object)
    failed=Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent);self.source=None;self.active=False
        self.deadline=QTimer(self);self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(lambda:self.fail('Система не определила местоположение за 30 секунд. Можно повторить или выбрать город вручную.'))

    def request(self):
        # Called only by the explicit consent button, on the foreground UI thread.
        self.cancel();self.active=True;self.deadline.start(30000)
        permission=QLocationPermission();permission.setAccuracy(QLocationPermission.Accuracy.Approximate)
        permission.setAvailability(QLocationPermission.Availability.WhenInUse)
        app=QApplication.instance();status=app.checkPermission(permission)
        if status==Qt.PermissionStatus.Undetermined:app.requestPermission(permission,self,self.permission_result)
        elif status==Qt.PermissionStatus.Denied:self.fail('Доступ к местоположению запрещён системой. Разреши его в настройках ОС или выбери город вручную.')
        else:self.start_source()

    def permission_result(self,permission):
        if not self.active:return
        if permission.status()==Qt.PermissionStatus.Granted:self.start_source()
        else:self.fail('Доступ к местоположению не разрешён. Ручной выбор города доступен без этого разрешения.')

    def start_source(self):
        if not self.active:return
        self.source=(QGeoPositionInfoSource.createSource('winrt',self) if sys.platform=='win32'
                     else QGeoPositionInfoSource.createDefaultSource(self))
        if self.source is None:
            self.fail('Системная геолокация недоступна. Проверь службу местоположения или выбери город вручную.');return
        self.source.positionUpdated.connect(self.position)
        self.source.errorOccurred.connect(self.source_error)
        self.source.requestUpdate(25000)

    def source_error(self,error):
        if error==QGeoPositionInfoSource.Error.NoError:return
        if error==QGeoPositionInfoSource.Error.AccessError:
            self.fail('ОС не разрешила доступ к геолокации. Проверь разрешение для классических приложений или выбери город вручную.')
        else:self.fail('Системная геолокация не дала координаты. Можно повторить или выбрать город вручную.')

    def position(self,info):
        if not self.active:return
        point=info.coordinate()
        if not info.isValid() or not point.isValid():self.fail('Система вернула некорректные координаты.');return
        accuracy=info.attribute(QGeoPositionInfo.Attribute.HorizontalAccuracy) if info.hasAttribute(QGeoPositionInfo.Attribute.HorizontalAccuracy) else None
        self.cancel();self.found.emit(point.latitude(),point.longitude(),accuracy)

    def fail(self,message):
        if not self.active:return
        self.cancel();self.failed.emit(message)

    def cancel(self):
        self.active=False;self.deadline.stop()
        if self.source:
            self.source.stopUpdates();self.source.deleteLater();self.source=None


class NetworkResult(QObject):
    ready=Signal(int,str,object,str)


class StartupLocationRefresh(QObject):
    """One foreground fix per launch, only with the previously saved opt-in."""
    saved=Signal()
    failed=Signal(str)

    def __init__(self,parent):
        super().__init__(parent);self.locator=DeviceLocator(self);self.locator.found.connect(self.found)
        self.locator.failed.connect(self.failed.emit);self.network=NetworkResult();self.network.ready.connect(self.resolved)
        self.cancelled=False

    def cancel(self):
        self.cancelled=True;self.locator.cancel()

    def start(self):
        self.cancelled=False
        value=locations.current();self.initial_key=locations.location_key(value) if value else None
        if value and value['source']=='device' and store.get_setting('location_refresh_on_start',False):self.locator.request()

    def found(self,lat,lon,accuracy):
        signal=self.network
        def run():
            try:value=locations.from_device(lat,lon,accuracy);error=''
            except Exception:value=None;error='Не удалось уточнить часовой пояс. Используется сохранённое место.'
            signal.ready.emit(0,'startup',value,error)
        threading.Thread(target=run,name='orbita-startup-location',daemon=True).start()

    def resolved(self,token,kind,value,error):
        if self.cancelled:return
        current=locations.current()
        if not current or locations.location_key(current)!=self.initial_key or not store.get_setting('location_refresh_on_start',False):return
        if error:self.failed.emit(error);return
        try:locations.save(value,store.get_setting('weather_hours',[9,13,17]),True)
        except Exception:self.failed.emit('Новое место не сохранено. Используется прежнее.');return
        self.saved.emit()


class LocationDialog(QDialog):
    def __init__(self,owner,on_saved):
        super().__init__(owner);self.on_saved=on_saved;self.profile=locations.current();self.generation=0;self.closed=False
        self.setObjectName('locationDialog');self.setWindowTitle('Местоположение и погода')
        self.setAttribute(Qt.WA_DeleteOnClose);self.setWindowModality(Qt.WindowModal)
        self.setStyleSheet(STYLE+'QDialog {background:#1c273c;}')
        self.resize(640,min(780,self.screen().availableGeometry().height()-70))
        self.locator=DeviceLocator(self);self.locator.found.connect(self.device_found);self.locator.failed.connect(self.failed)
        self.network=NetworkResult();self.network.ready.connect(self.network_done)
        root=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);root.addWidget(scroll,1)
        content=QWidget();box=QVBoxLayout(content);box.setContentsMargins(12,8,18,8);box.setSpacing(12);scroll.setWidget(content)
        box.addWidget(label('Погода там, где ты',24,'#e9f5ff',True))
        note=label('Выбери место для прогноза и местного времени. Автоопределение запускается только по кнопке с твоего разрешения. IP-адрес и VPN для определения города не используются.',12)
        note.setWordWrap(True);box.addWidget(note)
        card=GlassCard();auto=QVBoxLayout(card)
        self.detect=btn('Разрешить и определить местоположение',self.detect_location,True);self.detect.setObjectName('detectLocation');auto.addWidget(self.detect)
        privacy=label('ОС может запросить доступ к геолокации. Для часового пояса и погоды координаты округляются примерно до 1 км и передаются Open-Meteo. Непрерывного отслеживания нет.',11)
        privacy.setWordWrap(True);auto.addWidget(privacy)
        if sys.platform=='win32':auto.addWidget(btn('Настройки геолокации Windows',lambda:QDesktopServices.openUrl(QUrl('ms-settings:privacy-location'))))
        box.addWidget(card)
        tabs=QTabWidget();box.addWidget(tabs)
        city=QWidget();citybox=QVBoxLayout(city);row=QHBoxLayout()
        self.query=QLineEdit();self.query.setObjectName('cityQuery');self.query.setPlaceholderText('Город, например: Казань')
        self.search=btn('Найти',self.search_city);self.query.returnPressed.connect(self.search_city)
        row.addWidget(self.query,1);row.addWidget(self.search);citybox.addLayout(row)
        self.results=QListWidget();self.results.setObjectName('cityResults');self.results.setFixedHeight(120)
        self.results.itemSelectionChanged.connect(self.choose_city);citybox.addWidget(self.results)
        hint=label('Поиск отправляет название города в Open-Meteo. Выбери результат с нужным регионом и часовым поясом.',11);hint.setWordWrap(True);citybox.addWidget(hint)
        tabs.addTab(city,'Найти город')
        coords=QWidget();coordbox=QVBoxLayout(coords);form=QFormLayout()
        self.lat=QDoubleSpinBox();self.lat.setRange(-90,90);self.lat.setDecimals(4)
        self.lon=QDoubleSpinBox();self.lon.setRange(-180,180);self.lon.setDecimals(4)
        self.zone=QComboBox();self.zone.setEditable(True);self.zone.addItems(sorted(available_timezones()));self.zone.setCurrentText(store.timezone_name())
        form.addRow('Широта',self.lat);form.addRow('Долгота',self.lon);form.addRow('Часовой пояс IANA',self.zone);coordbox.addLayout(form)
        coordbox.addWidget(btn('Использовать координаты',self.choose_coordinates));tabs.addTab(coords,'Координаты без поиска')
        if self.profile:self.lat.setValue(self.profile['latitude']);self.lon.setValue(self.profile['longitude'])
        self.name=QLineEdit(self.profile['name'] if self.profile else '');self.name.setObjectName('locationName');self.name.setPlaceholderText('Название выбранного места')
        box.addWidget(self.name)
        self.preview=label('',12,'#b9eede');self.preview.setWordWrap(True);box.addWidget(self.preview)
        self.refresh_on_start=QCheckBox('Повторять определение при открытии Орбиты');self.refresh_on_start.setObjectName('locationRefreshOnStart')
        self.refresh_on_start.setChecked(store.get_setting('location_refresh_on_start',False));box.addWidget(self.refresh_on_start)
        hours_form=QFormLayout();self.hours=[]
        for title,value in zip(('Утро','День','Вечер'),store.get_setting('weather_hours',[9,13,17])):
            hour=QSpinBox();hour.setRange(0,23);hour.setValue(value);hour.setSuffix(':00');self.hours.append(hour);hours_form.addRow(title,hour)
        box.addWidget(label('Часы погодных карточек · время выбранного места',12));box.addLayout(hours_form)
        scheduling=label('Погода и тихие часы используют выбранное место. Существующие напоминания сохраняют свой часовой пояс; его можно изменить в настройках каждой задачи. При переезде выбери новое место здесь.',11)
        scheduling.setWordWrap(True);box.addWidget(scheduling)
        self.status=label('',12,'#efca91');self.status.setObjectName('locationStatus');self.status.setWordWrap(True);box.addWidget(self.status);box.addStretch()
        actions=QHBoxLayout();actions.addWidget(btn('Позже',self.close));self.save_button=btn('Сохранить место',self.save,True);self.save_button.setObjectName('saveLocation');actions.addWidget(self.save_button);root.addLayout(actions)
        self.update_preview()

    def update_preview(self):
        self.save_button.setEnabled(self.profile is not None)
        self.refresh_on_start.setEnabled(bool(self.profile and self.profile['source']=='device'))
        if not self.refresh_on_start.isEnabled():self.refresh_on_start.setChecked(False)
        self.preview.setText((f"{self.profile['latitude']:.4f}, {self.profile['longitude']:.4f} · {self.profile['timezone']}"+
            (f"\nТочность системы: около {self.profile['accuracy_m']:.0f} м" if self.profile.get('accuracy_m') is not None else '')) if self.profile else 'Место пока не выбрано.')

    def busy(self,message):
        self.generation+=1;self.status.setText(message);self.detect.setDisabled(True);self.search.setDisabled(True);self.query.setDisabled(True);self.save_button.setDisabled(True)
        return self.generation

    def idle(self):
        self.detect.setEnabled(True);self.search.setEnabled(True);self.query.setEnabled(True);self.update_preview()

    def failed(self,message):
        self.status.setText(message);self.idle()

    def network_job(self,kind,work):
        token=self.busy('Определяю часовой пояс…' if kind=='device' else 'Ищу города…');signal=self.network
        def run():
            try:result=work();error=''
            except Exception:result=None;error='Сервис недоступен или вернул неполные данные. Место не изменено. Повтори позже или задай координаты и часовой пояс вручную.'
            signal.ready.emit(token,kind,result,error)
        threading.Thread(target=run,name='orbita-location',daemon=True).start()

    def detect_location(self):
        self.busy('Ожидаю разрешение и координаты от системы…');self.locator.request()

    def device_found(self,latitude,longitude,accuracy):
        self.network_job('device',lambda:locations.from_device(latitude,longitude,accuracy))

    def search_city(self):
        query=self.query.text().strip()
        if len(query)<2:self.failed('Введи хотя бы два символа названия города.');return
        self.locator.cancel();self.network_job('search',lambda:locations.search_cities(query))

    def network_done(self,token,kind,result,error):
        if self.closed or token!=self.generation:return
        if error:self.failed(error);return
        if kind=='device':self.profile=result;self.name.setText(result['name']);self.status.setText('Координаты определены системой. Проверь место и нажми «Сохранить место».')
        else:
            self.results.clear()
            for value in result:
                item=QListWidgetItem(value['name']+' · '+value.get('region','')+' · '+value['timezone']);item.setData(Qt.UserRole,value);self.results.addItem(item)
            self.status.setText('Выбери город из списка.' if result else 'Города не найдены. Попробуй другое название или введи координаты.')
        self.idle()

    def choose_city(self):
        item=self.results.currentItem()
        if not item:return
        self.generation+=1;self.locator.cancel();self.profile=item.data(Qt.UserRole);self.name.setText(self.profile['name']);self.idle();self.status.setText('Город выбран. Проверь часы карточек и сохрани место.')

    def choose_coordinates(self):
        try:self.profile=locations.validate(dict(name=self.name.text().strip() or 'Моё место',latitude=self.lat.value(),longitude=self.lon.value(),timezone=self.zone.currentText(),source='manual'))
        except (ValueError,KeyError) as exc:self.failed(str(exc));return
        self.generation+=1;self.locator.cancel();self.name.setText(self.profile['name']);self.idle();self.status.setText('Координаты выбраны без сетевого поиска.')

    def save(self):
        if not self.profile:return
        try:
            value=dict(self.profile,name=self.name.text().strip());locations.save(value,[hour.value() for hour in self.hours],self.refresh_on_start.isChecked())
        except Exception as exc:self.failed('Место не сохранено: '+str(exc));return
        self.on_saved();self.close()

    def closeEvent(self,event):
        self.finish_cleanup();super().closeEvent(event)

    def finish_cleanup(self):
        if self.closed:return
        self.closed=True;self.generation+=1;self.locator.cancel();locations.defer_setup()

    def reject(self):
        self.finish_cleanup();super().reject()
