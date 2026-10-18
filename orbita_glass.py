"""Orbita: animated Qt desktop surface and local automation inbox."""
import argparse
import ctypes
from datetime import datetime
import json
import logging
import math
from pathlib import Path
import sys
import time
import threading
from copy import deepcopy
from datetime import timedelta
from zoneinfo import ZoneInfo,available_timezones

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, QPoint, QDateTime, QTime, QPropertyAnimation, QEasingCurve,QUrl,QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QLinearGradient, QRadialGradient, QPainterPath, QFont, QIcon, QPixmap, QAction,QDesktopServices
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QDialog, QCheckBox, QTextBrowser, QGridLayout,
    QSizeGrip, QSystemTrayIcon, QMenu, QStackedWidget, QLineEdit, QTextEdit,
    QComboBox, QSpinBox, QDateTimeEdit, QTimeEdit, QFormLayout, QMessageBox)

import desktop_store as store
from automation_engine import Engine, quiet_now
from automation_models import new_task, next_due, schedule_text, parse_time
import windows_integration
from learning_ui import LearningPage,LessonDialog
from projects_ui import ProjectsPage,ProjectDialog
from ui_theme import STYLE,install_theme
from ui_components import label,btn,GlassCard,NavigationBar
from app_config import VERSION,program_dir,docs_dir,timezone_from_settings
from today_ui import TodayOverview
import today_service
import agenda_service
from day_ui import WeatherPanel,TomorrowPage
import location_service as locations
from location_ui import LocationDialog,StartupLocationRefresh
from onboarding_ui import WelcomeDialog,system_timezone
import preferences_service as preferences


def condition(code, daylight=True):
    if code == 0:
        return ('sun' if daylight else 'moon', 'Ясно')
    if code in (1, 2):
        return ('partly' if daylight else 'nightcloud', 'Переменная облачность')
    if code == 3:
        return 'cloud', 'Пасмурно'
    if code in (45, 48):
        return 'fog', 'Туман'
    if code in (71, 73, 75, 77, 85, 86):
        return 'snow', 'Снег'
    if code in (95, 96, 99):
        return 'storm', 'Гроза'
    if code in (56, 57, 66, 67):
        return 'rain', 'Ледяные осадки'
    if code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
        return 'rain', 'Дождь'
    return 'unknown', 'Нет описания'


class WeatherArt(QWidget):
    """Resolution-independent weather scene; all motion is painted, no GIF dependencies."""
    def __init__(self, kind='unknown', parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setMinimumHeight(96)
        self.phase = 0
        self.motion_enabled=True;self.scene_animated=kind!='unknown'
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)

    def set_scene(self,kind,animated=True):
        self.kind=kind;self.scene_animated=animated and kind!='unknown'
        self.sync_timer();self.update()

    def set_motion(self,enabled):
        self.motion_enabled=enabled;self.sync_timer()

    def sync_timer(self):
        active=self.motion_enabled and self.scene_animated and self.isVisible() and not self.window().isMinimized()
        if active and not self.timer.isActive():self.timer.start(67)
        elif not active:self.timer.stop()

    def advance(self):
        if self.isVisible() and not self.window().isMinimized() and not self.visibleRegion().isEmpty():
            self.phase += 0.067
            self.update()

    def showEvent(self,event):
        super().showEvent(event)
        self.sync_timer()

    def hideEvent(self,event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale = min(self.width() / 180, self.height() / 112)
        p.translate(self.width()/2, self.height()/2)
        p.scale(scale, scale)
        t = self.phase
        palette = {'sun':'#ffd38b','moon':'#b6caff','partly':'#ffe0a5',
                   'rain':'#79b9ff','snow':'#d1eeff','storm':'#bba2ff','fog':'#b4cad9'}
        glow = QColor(palette.get(self.kind, '#9fb9e9'))
        gradient = QRadialGradient(0, 0, 70)
        glow.setAlpha(45)
        gradient.setColorAt(0, glow)
        gradient.setColorAt(1, QColor(0,0,0,0))
        p.setPen(Qt.NoPen)
        p.setBrush(gradient)
        p.drawEllipse(QRectF(-75,-65,150,130))
        if self.kind in ('sun','partly','moon','nightcloud'):
            moon = self.kind in ('moon','nightcloud')
            cx, cy = ((-22,-13) if self.kind in ('partly','nightcloud') else (0,-3))
            cy += math.sin(t) * 2
            if not moon:
                p.save()
                p.translate(cx,cy)
                p.rotate(t*8)
                p.setPen(QPen(QColor('#f7cf8f'), 3, Qt.SolidLine, Qt.RoundCap))
                for i in range(8):
                    a=i*math.pi/4
                    p.drawLine(QPointF(math.cos(a)*30,math.sin(a)*30),QPointF(math.cos(a)*38,math.sin(a)*38))
                p.restore()
            p.setPen(Qt.NoPen)
            disk = QLinearGradient(cx-20,cy-20,cx+20,cy+22)
            disk.setColorAt(0,QColor('#fff0be' if not moon else '#edf2ff'))
            disk.setColorAt(1,QColor('#f1ae65' if not moon else '#8ea6df'))
            p.setBrush(disk)
            if moon:
                path=QPainterPath()
                path.addEllipse(QRectF(cx-23,cy-23,46,46))
                cut=QPainterPath()
                cut.addEllipse(QRectF(cx-9,cy-30,43,43))
                p.drawPath(path.subtracted(cut))
                p.setBrush(QColor('#dce9ff'))
                for x,y in [(35,-30),(43,5),(-36,22)]:
                    p.drawEllipse(QPointF(x,y),1.7+0.5*math.sin(t+x),1.7+0.5*math.sin(t+x))
            else:
                p.drawEllipse(QRectF(cx-22,cy-22,44,44))
        if self.kind not in ('sun','moon','unknown'):
            p.save()
            p.translate(math.sin(t*.7)*3, math.sin(t)*2)
            path=QPainterPath()
            path.setFillRule(Qt.WindingFill)
            path.addRoundedRect(QRectF(-46,-6,91,31),15,15)
            path.addEllipse(QRectF(-35,-26,43,43))
            path.addEllipse(QRectF(-10,-34,49,51))
            path=path.simplified()
            cloud=QLinearGradient(0,-35,0,26)
            cloud.setColorAt(0,QColor('#e6efff'))
            cloud.setColorAt(1,QColor('#8196bd'))
            p.setBrush(cloud)
            p.setPen(QPen(QColor(255,255,255,80),1))
            p.drawPath(path)
            p.restore()
        if self.kind in ('rain','snow','storm'):
            for i in range(6):
                x=-35+i*14
                y=26+((t*23+i*9)%27)
                alpha=int(200*(1-(y-26)/40))
                p.setPen(QPen(QColor(150,210,255,alpha),2,Qt.SolidLine,Qt.RoundCap))
                if self.kind=='snow':
                    x+=math.sin(t+i)*4
                    for a in (0,math.pi/3,2*math.pi/3):
                        p.drawLine(QPointF(x-math.cos(a)*3,y-math.sin(a)*3),QPointF(x+math.cos(a)*3,y+math.sin(a)*3))
                else:
                    p.drawLine(QPointF(x,y),QPointF(x-3,y+7))
            if self.kind=='storm':
                path=QPainterPath(QPointF(5,10))
                for point in [(-10,32),(1,32),(-4,49),(21,24),(10,24),(17,10)]:
                    path.lineTo(*point)
                path.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255,219,120,int(180+70*math.sin(t*3))))
                p.drawPath(path)
        if self.kind=='fog':
            for i in range(3):
                shift=math.sin(t+i)*6
                p.setPen(QPen(QColor(197,222,235,160-i*25),3,Qt.SolidLine,Qt.RoundCap))
                p.drawLine(QPointF(-47+shift,28+i*9),QPointF(42+shift-i*9,28+i*9))
        if self.kind=='unknown':
            p.setPen(QColor('#b8c8dd'))
            p.setFont(QFont('Segoe UI',24))
            p.drawText(QRectF(-40,-30,80,60),Qt.AlignCenter,'—')


class PeriodCard(GlassCard):
    def __init__(self,title,time_text,tint):
        super().__init__(tint)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(16,16,16,17)
        top=QHBoxLayout()
        top.addWidget(label(title,14,'#edf2ff',True))
        top.addStretch()
        self.hour_label=label(time_text,11,'#b3bdd2');top.addWidget(self.hour_label)
        layout.addLayout(top)
        self.art=WeatherArt()
        layout.addWidget(self.art)
        self.temperature=label('—°',36,'#f7f9ff',True)
        layout.addWidget(self.temperature)
        self.description=label('Ожидает прогноза',11)
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.feels=label('Ощущается —',11)
        layout.addWidget(self.feels)
        self.metrics=label('Ветер —\nОсадки —\nВлажность —',11)
        self.metrics.setWordWrap(True)
        layout.addWidget(self.metrics)

    def apply(self,hourly,date,hour):
        from weather import period_index
        i=period_index(hourly,date,hour)
        actual=hourly['time'][i][11:16]
        self.hour_label.setText(actual if actual==f'{hour:02d}:00' else '≈ '+actual)
        def value(key):
            result=hourly[key][i]
            if result is None: raise ValueError('Incomplete forecast')
            return result
        kind,description=condition(value('weather_code'),bool(value('is_day')))
        self.art.set_scene(kind)
        self.temperature.setText(f"{value('temperature_2m'):+.0f}°")
        self.description.setText(description)
        self.feels.setText(f"Ощущается {value('apparent_temperature'):+.0f}°")
        self.metrics.setText(f"Ветер {value('wind_speed_10m'):.1f} м/с\n"
                             f"Порывы {value('wind_gusts_10m'):.1f} м/с\n"
                             f"Осадки {value('precipitation_probability'):.0f}% · {value('precipitation'):.1f} мм/ч\n"
                             f"Влажность {value('relative_humidity_2m'):.0f}%")

    def clear(self,message='Ожидает прогноза'):
        self.art.set_scene('cloud',animated=False);self.temperature.setText('—°');self.description.setText(message)
        self.feels.setText('Ощущается —');self.metrics.setText('Ветер —\nОсадки —\nВлажность —')


class Toast(GlassCard):
    def __init__(self,row,owner):
        super().__init__('#455a78')
        self.owner=owner
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(390)
        layout=QVBoxLayout(self); layout.setContentsMargins(24,18,24,20)
        top=QHBoxLayout(); top.addWidget(label('◉  ОРБИТА  /  '+row['category'],11,'#a3eed8',True)); top.addStretch()
        close=btn('×',self.close); close.setFixedSize(30,30); close.setStyleSheet('border:none; padding:0;')
        top.addWidget(close); layout.addLayout(top)
        title=label(row['title'],16,'#f4f7ff',True); title.setWordWrap(True); layout.addWidget(title)
        body=label(row['body'][:150]+('…' if len(row['body'])>150 else ''),12)
        body.setWordWrap(True); layout.addWidget(body)
        layout.addWidget(btn('Открыть занятие' if (row.get('target') or '').startswith('lesson:') else 'Открыть проект' if (row.get('target') or '').startswith('project:') else 'Посмотреть',lambda:self.open(row)))
        if row.get('action_state')=='pending':
            actions=QHBoxLayout()
            actions.addWidget(btn('Выполнено',lambda:self.act(row,'done'),True))
            actions.addWidget(btn('+15 минут',lambda:self.act(row,'snooze')))
            layout.addLayout(actions)
        self.adjustSize()
        area=QApplication.primaryScreen().availableGeometry()
        end=QPoint(area.right()-self.width()-20,area.bottom()-self.height()-20)
        self.move(end+QPoint(50,0)); self.setWindowOpacity(0)
        self.slide=QPropertyAnimation(self,b'pos',self)
        self.slide.setDuration(450); self.slide.setStartValue(self.pos()); self.slide.setEndValue(end)
        self.slide.setEasingCurve(QEasingCurve.OutCubic)
        self.fade=QPropertyAnimation(self,b'windowOpacity',self)
        self.fade.setDuration(450); self.fade.setStartValue(0.0); self.fade.setEndValue(1.0)
        self.show(); self.slide.start(); self.fade.start()
        QTimer.singleShot(int(store.get_setting('toast_seconds',13))*1000,self.close)

    def open(self,row):
        self.owner.open_event(row); self.close()

    def act(self,row,action):
        store.reminder_action(row['id'],action); self.owner.tick(); self.close()


class Window(QWidget):
    def __init__(self):
        install_theme(QApplication.instance())
        super().__init__()
        preferences.bootstrap(system_timezone())
        self.setWindowTitle('Орбита · Glass')
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.pinned=store.get_setting('topmost',True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint,self.pinned)
        area=QApplication.primaryScreen().availableGeometry()
        self.resize(min(670,area.width()-40),min(890,area.height()-40))
        self.setMinimumSize(540,480)
        self.move(area.left()+35,area.top()+20)
        self.engine=Engine()
        self.revision_reader=store.RevisionReader()
        self.has_pending=True
        self.quitting=False; self.shutdown_thread=None
        self.last_revision=-1; self.settings_cache={}; self.snapshot_fingerprint=None
        self.saved_snapshot=None; self.saved_forecasts=store.get_setting('weather_forecasts',{});self.snapshot_minute=None
        self.task_fingerprint=None; self.log_fingerprint=None
        self.tasks_visible_count=20;self.feed_dirty=True;self.visual_dirty=True
        self.today_minute=None;self.tomorrow_minute=None
        self.learning_dialogs={}
        self.project_dialogs={}
        self.location_dialog=None;self.welcome_dialog=None;self.weather_refresh_pending=False
        self.location_profile=locations.current();self.display_zone=store.local_zone()
        self.weather_hours=store.get_setting('weather_hours',[9,13,17])
        self.location_refresher=StartupLocationRefresh(self);self.location_refresher.saved.connect(lambda:self.location_changed(automatic=True))
        self.location_refresher.failed.connect(self.location_failed)
        self.filter='Все'; self.fingerprint=None
        self.toasts=[]; self.toast_queue=[]
        self.build()
        self.setup_tray()
        geometry=store.get_setting('window_geometry')
        if geometry:
            self.resize(max(540,min(geometry[2],area.width())),max(480,min(geometry[3],area.height())))
            self.move(max(area.left(),min(geometry[0],area.right()-self.width()+1)),
                      max(area.top(),min(geometry[1],area.bottom()-self.height()+1)))
        self.apply_snapshot(store.get_setting('weather_snapshot'))
        self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(1300)
        self.tick()
        self.engine.start()

    def showEvent(self,event):
        super().showEvent(event)
        self.apply_window_surface()
        if hasattr(self,'timer'):self.tick()

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QEvent.WindowStateChange:
            for art in self.findChildren(WeatherArt):art.sync_timer()

    def paintEvent(self,event):
        # Transparent children repaint the parent behind every animation frame.
        # Cache only the static surface, invalidating on size or monitor scale.
        key=(self.width(),self.height(),self.devicePixelRatioF())
        if getattr(self,'surface_key',None)!=key:
            self.surface_key=key
            self.surface=QPixmap(round(self.width()*key[2]),round(self.height()*key[2]))
            self.surface.setDevicePixelRatio(key[2]);self.surface.fill(Qt.transparent)
            painter=QPainter(self.surface);self.paint_surface(painter);painter.end()
        p=QPainter(self);p.setCompositionMode(QPainter.CompositionMode_Source);p.drawPixmap(0,0,self.surface)

    def paint_surface(self,p):
        p.setRenderHint(QPainter.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(),Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        rect=QRectF(self.rect()).adjusted(1,1,-1,-1)
        path=QPainterPath(); path.addRoundedRect(rect,28,28)
        p.setClipPath(path)
        background=QLinearGradient(0,0,self.width(),self.height())
        background.setColorAt(0,QColor(25,39,56,250))
        background.setColorAt(.5,QColor(24,28,49,249))
        background.setColorAt(1,QColor(17,29,40,252))
        p.fillRect(self.rect(),background)
        for x,y,r,color in [(self.width()*.9,60,330,QColor(143,117,209,42)),(0,420,340,QColor(67,167,160,27))]:
            glow=QRadialGradient(x,y,r); glow.setColorAt(0,color); glow.setColorAt(1,QColor(0,0,0,0))
            p.fillRect(self.rect(),glow)
        p.setClipping(False); p.setPen(QPen(QColor(220,235,255,60),1)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect,28,28)

    def apply_window_surface(self):
        windows_integration.clear_window_backdrop(int(self.winId()))

    def build(self):
        outer=QVBoxLayout(self); outer.setContentsMargins(24,16,24,12); outer.setSpacing(12)
        header=QHBoxLayout()
        brand=label('◉  ОРБИТА',18,'#c3f5e5',True)
        brand.setToolTip('Перетаскивай панель за свободную область шапки')
        header.addWidget(brand); header.addStretch()
        self.pin=btn('Закреплено' if self.pinned else 'Поверх окон',self.toggle_pin)
        self.pin.setToolTip('Закрепить поверх остальных окон'); header.addWidget(self.pin)
        settings=btn('⚙',self.settings);settings.setObjectName('openSettings');settings.setAccessibleName('Настройки Орбиты');settings.setProperty('windowControl',True);settings.setFixedSize(36,36);settings.setToolTip('Настройки');header.addWidget(settings)
        minimize=btn('−',self.showMinimized);minimize.setProperty('windowControl',True);minimize.setFixedSize(36,36);minimize.setToolTip('Свернуть окно')
        close=btn('×',self.close);close.setProperty('windowControl',True);close.setProperty('closeControl',True);close.setFixedSize(36,36);close.setToolTip('Скрыть в трей · автоматизации продолжают работать')
        header.addWidget(minimize);header.addWidget(close)
        outer.addLayout(header)
        self.clock=label('',12); outer.addWidget(self.clock)
        self.location_status=label('',11,'#efca91');self.location_status.setWordWrap(True);self.location_status.hide();outer.addWidget(self.location_status)
        self.nav_pages=[0,5,1,2,3,4]
        self.navigation=NavigationBar(['Сегодня','Завтра','Автоматизации','Журнал','Обучение','Проекты'],lambda index:self.switch_page(self.nav_pages[index]))
        self.nav_buttons=[self.navigation.buttons[self.nav_pages.index(index)] for index in range(6)];outer.addWidget(self.navigation)
        scroll=QScrollArea(); scroll.setWidgetResizable(True)
        content=QWidget(); content.setObjectName('scrollContent')
        content.setStyleSheet('#scrollContent {background:transparent;}')
        self.content_layout=QVBoxLayout(content); self.content_layout.setContentsMargins(0,2,6,0); self.content_layout.setSpacing(14)
        intro=QHBoxLayout(); intro.addWidget(label('Сегодня',24,'#f0f5ff',True)); intro.addStretch()
        self.content_layout.addLayout(intro)
        self.today_overview=TodayOverview(self);self.content_layout.addWidget(self.today_overview)
        self.weather_panel=WeatherPanel(self,PeriodCard);self.content_layout.addWidget(self.weather_panel)
        self.weather_heading=self.weather_panel.heading;self.periods=self.weather_panel.periods
        self.forecast_stamp=self.weather_panel.stamp;self.refresh=self.weather_panel.update_button
        self.schedule=label('',11); self.content_layout.addWidget(self.schedule)
        history_header=QHBoxLayout(); history_header.addWidget(label('Лента событий',18,'#edf3ff',True)); history_header.addStretch()
        history_header.addWidget(btn('Прочитать всё',self.read_all)); self.content_layout.addLayout(history_header)
        filter_names=['Все','Погода','Напоминания','Обучение','Проекты']
        filters=NavigationBar(filter_names,lambda index:self.set_filter(filter_names[index]))
        self.filter_buttons=dict(zip(filter_names,filters.buttons));self.content_layout.addWidget(filters)
        self.feed=QVBoxLayout(); self.feed.setSpacing(10); self.content_layout.addLayout(self.feed)
        self.content_layout.addStretch()
        scroll.setWidget(content)
        self.pages=QStackedWidget(); self.pages.addWidget(scroll)
        for name in ['tasks','logs']:
            page_scroll=QScrollArea(); page_scroll.setWidgetResizable(True)
            page=QWidget(); page.setObjectName(name+'Content'); page.setStyleSheet('#'+name+'Content {background:transparent;}')
            box=QVBoxLayout(page); box.setContentsMargins(0,2,6,8); box.setSpacing(12)
            setattr(self,name+'_layout',box)
            page_scroll.setWidget(page); self.pages.addWidget(page_scroll)
        self.learning_page=LearningPage(self)
        learning_scroll=QScrollArea(); learning_scroll.setWidgetResizable(True); learning_scroll.setWidget(self.learning_page)
        self.pages.addWidget(learning_scroll)
        self.projects_page=ProjectsPage(self)
        projects_scroll=QScrollArea();projects_scroll.setWidgetResizable(True);projects_scroll.setWidget(self.projects_page)
        self.pages.addWidget(projects_scroll)
        self.tomorrow_page=TomorrowPage(self,PeriodCard)
        tomorrow_scroll=QScrollArea();tomorrow_scroll.setWidgetResizable(True);tomorrow_scroll.setWidget(self.tomorrow_page)
        self.pages.addWidget(tomorrow_scroll)
        outer.addWidget(self.pages,1)
        footer=QHBoxLayout(); self.status=label('●  Локальный центр автоматизаций',11,'#99d9c5'); footer.addWidget(self.status); footer.addStretch()
        footer.addWidget(btn('О приложении',self.about)); footer.addWidget(QSizeGrip(self))
        outer.addLayout(footer)
        self.set_filter('Все')
        self.switch_page(0)

    def switch_page(self,index):
        self.pages.setCurrentIndex(index)
        for i,item in enumerate(self.nav_buttons):
            item.setProperty('active',i==index); item.style().unpolish(item); item.style().polish(item)
        if index==1:self.redraw_tasks()
        if index==2:self.redraw_logs()
        if index==3:self.learning_page.refresh()
        if index==4:self.projects_page.refresh()
        if index==0:self.refresh_today();self.redraw()
        if index==5:self.refresh_tomorrow()

    def refresh_today(self):
        self.today_overview.refresh(today_service.snapshot())
        self.today_minute=datetime.now(self.display_zone).strftime('%Y-%m-%d-%H-%M')

    def refresh_tomorrow(self):
        self.tomorrow_page.refresh(agenda_service.snapshot())
        self.tomorrow_minute=datetime.now(self.display_zone).strftime('%Y-%m-%d-%H-%M')
        self.apply_snapshot(self.saved_snapshot)

    def setup_tray(self):
        icon=QPixmap(64,64); icon.fill(Qt.transparent)
        painter=QPainter(icon); painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor('#1a2b42')); painter.setPen(Qt.NoPen); painter.drawRoundedRect(1,1,62,62,18,18)
        painter.setPen(QPen(QColor('#a3eed8'),6)); painter.drawEllipse(14,14,36,36)
        painter.setBrush(QColor('#eef8ff')); painter.setPen(Qt.NoPen); painter.drawEllipse(39,11,11,11); painter.end()
        self.setWindowIcon(QIcon(icon))
        self.tray=QSystemTrayIcon(QIcon(icon),self); self.tray.setToolTip('Орбита · автоматизации')
        menu=QMenu()
        menu.addAction('Открыть Орбиту',self.reveal)
        self.pause_action=menu.addAction('Приостановить автоматизации',self.toggle_pause)
        self.quiet_action=menu.addAction('Не беспокоить',self.toggle_dnd); self.quiet_action.setCheckable(True)
        menu.addSeparator(); menu.addAction('Полностью выйти',self.quit_app)
        self.tray.setContextMenu(menu); self.tray_menu=menu
        self.tray.activated.connect(lambda reason:self.reveal() if reason in (QSystemTrayIcon.Trigger,QSystemTrayIcon.DoubleClick) else None)
        if QSystemTrayIcon.isSystemTrayAvailable():self.tray.show()

    def reveal(self):
        self.showNormal(); self.raise_(); self.activateWindow()
        if getattr(self,'location_prompt_on_reveal',False):
            self.location_prompt_on_reveal=False;self.offer_location_setup()

    def offer_location_setup(self):
        if store.get_setting('onboarding_pending',False):
            self.show_welcome()
        elif not store.get_setting('location_setup_complete',False):self.configure_location()
        elif store.get_setting('location_refresh_on_start',False):self.location_refresher.start()

    def show_welcome(self):
        if self.welcome_dialog is not None:self.welcome_dialog.raise_();return
        win=WelcomeDialog(self);self.welcome_dialog=win
        win.finished.connect(lambda result:setattr(self,'welcome_dialog',None));win.show()

    def configure_location(self):
        self.location_refresher.cancel()
        if self.location_dialog is not None:
            self.location_dialog.showNormal();self.location_dialog.raise_();self.location_dialog.activateWindow();return
        win=LocationDialog(self,self.location_changed);self.location_dialog=win
        win.finished.connect(lambda result:setattr(self,'location_dialog',None) if self.location_dialog is win else None);win.show()

    def location_changed(self,automatic=False):
        self.location_status.clear();self.location_status.hide()
        self.weather_refresh_pending=not automatic or not store.get_setting('paused',False);self.last_revision=-1;self.tick()

    def location_failed(self,message):
        self.location_status.setText(message+' Последнее выбранное место сохранено.');self.location_status.show()

    def toggle_pause(self):
        store.set_setting('paused',not store.get_setting('paused',False)); self.tick()

    def toggle_dnd(self):
        store.set_setting('dnd',not store.get_setting('dnd',False)); self.tick()

    def clear_layout(self,layout):
        while layout.count():
            item=layout.takeAt(0)
            if item.widget():item.widget().deleteLater()

    def redraw_tasks(self):
        revision=store.revision()
        fingerprint=(revision,self.tasks_visible_count)
        if self.task_fingerprint==fingerprint:return
        self.task_fingerprint=fingerprint; self.clear_layout(self.tasks_layout)
        tasks=store.tasks();latest_by_task=store.latest_runs();paused=store.get_setting('paused',False)
        self.tasks_layout.addWidget(label('Автоматизации',24,'#f0f5ff',True))
        controls=GlassCard(); controls_box=QHBoxLayout(controls)
        controls_box.addWidget(btn('+ Напоминание',self.edit_task,True))
        controls_box.addWidget(btn('Продолжить' if paused else 'Пауза всех задач',self.toggle_pause))
        self.tasks_layout.addWidget(controls)
        self.tasks_layout.addWidget(label(f'Показано {min(len(tasks),self.tasks_visible_count)} из {len(tasks)}',12))
        descriptions={'weather':'Почасовой прогноз выбранного места','reminder':'Личное напоминание','audit':'Обзор реальных журналов за 7 дней',
                      'learning':'Диагностика и практика Db2 · продолжение текущего занятия'}
        states={'running':'Выполняется','retry':'Ожидает повтора','queued':'В очереди','failed':'Ошибка',
                'success':'Готово','skipped':'Пропущено по правилам','cancelled':'Отменено'}
        now=datetime.now(store.LOCAL)
        for task in tasks[:self.tasks_visible_count]:
            card=GlassCard('#3b4b60'); box=QVBoxLayout(card); box.setContentsMargins(18,16,18,16)
            row=QHBoxLayout(); row.addWidget(label(task['name'],16,'#f1f5ff',True)); row.addStretch()
            latest=latest_by_task.get(task['id'])
            state=('Приостановлена' if not task['enabled'] else 'Общая пауза' if paused
                   else states.get(latest['status'],'Включена') if latest else 'Включена')
            row.addWidget(label(state,11,'#a3eed8' if task['enabled'] else '#a6b1c6')); box.addLayout(row)
            box.addWidget(label('Напоминание о проекте' if task['config'].get('project_id') else descriptions[task['kind']],12))
            spec=label(schedule_text(task),12); spec.setWordWrap(True); box.addWidget(spec)
            upcoming=next_due(task,now)
            if task['enabled'] and latest and latest['status']=='retry' and latest['retry_at']:
                upcoming=parse_time(latest['retry_at'])
            next_text='Следующий запуск: '+(upcoming.astimezone(self.display_zone).strftime('%d.%m %H:%M') if upcoming else 'выключен')+' · местное время'
            if paused:next_text+=' · общая пауза'
            box.addWidget(label(next_text,12))
            if latest:
                text=f"Последний: {parse_time(latest['scheduled_at']).astimezone(self.display_zone):%d.%m %H:%M} · {states.get(latest['status'],latest['status'])}"
                if latest['summary']:text+=' · '+latest['summary']
                last=label(text,11); last.setWordWrap(True); box.addWidget(last)
            actions=QHBoxLayout()
            run=btn('Запустить сейчас',lambda checked=False,t=task:self.run_task(t['id']))
            run.setDisabled(bool(latest and latest['status']=='running')); actions.addWidget(run)
            actions.addWidget(btn('Пауза' if task['enabled'] else 'Включить',lambda checked=False,t=task:self.toggle_task(t)))
            actions.addWidget(btn('Настроить',lambda checked=False,t=task:self.edit_task(t)))
            actions.addWidget(btn('История',lambda checked=False,t=task:self.show_task_log(t)))
            box.addLayout(actions); self.tasks_layout.addWidget(card)
        if len(tasks)>self.tasks_visible_count:
            more=btn('Показать ещё 20',self.more_tasks);more.setObjectName('moreTasks');self.tasks_layout.addWidget(more)
        self.tasks_layout.addStretch()

    def more_tasks(self):
        self.tasks_visible_count+=20;self.redraw_tasks()

    def toggle_task(self,task):
        if task['kind']=='weather' and not task['enabled'] and not locations.current():
            self.configure_location();return
        task=deepcopy(task); task['enabled']=not task['enabled']
        try:store.save_task(task)
        except ValueError as exc:QMessageBox.warning(self,'Проверь проект',str(exc));return
        self.tick()

    def run_task(self,task_id):
        if next(t for t in store.tasks() if t['id']==task_id)['kind']=='weather' and not locations.current():
            self.configure_location();return
        self.engine.run_now(task_id); self.tick()

    def redraw_logs(self):
        revision=store.revision()
        if self.log_fingerprint==revision:return
        self.log_fingerprint=revision; self.clear_layout(self.logs_layout)
        self.logs_layout.addWidget(label('Журнал запусков',24,'#f0f5ff',True))
        self.logs_layout.addWidget(label('Последние 60 запусков · уведомления хранятся отдельно',12))
        names={t['id']:t['name'] for t in store.tasks()}
        rows=store.runs(limit=60)
        if not rows:self.logs_layout.addWidget(label('Запусков пока нет. Выполни задачу вручную.',13))
        states={'queued':'В очереди','running':'Выполняется','retry':'Повтор','success':'Успешно',
                'failed':'Ошибка','skipped':'Пропущено','cancelled':'Отменено'}
        for row in rows:
            card=GlassCard(); box=QVBoxLayout(card); box.setContentsMargins(16,12,16,12)
            box.addWidget(label(names.get(row['task_id'],row['task_id']),15,'#eaf2ff',True))
            box.addWidget(label(f"{parse_time(row['scheduled_at']).astimezone(self.display_zone):%d.%m %H:%M} · {states.get(row['status'],row['status'])} · попыток {row['attempts']}",12))
            note=label(row['error'] or row['summary'] or 'Ожидает выполнения',12); note.setWordWrap(True); box.addWidget(note)
            box.addWidget(btn('Подробности',lambda checked=False,r=row:self.run_details(r)))
            self.logs_layout.addWidget(card)
        self.logs_layout.addStretch()

    def run_details(self,row):
        win=self.dialog('Подробности запуска'); box=QVBoxLayout(win)
        names={t['id']:t['name'] for t in store.tasks()}
        states={'queued':'В очереди','running':'Выполняется','retry':'Ожидает повторной попытки','success':'Успешно','failed':'Ошибка','skipped':'Пропущено','cancelled':'Отменено'}
        lines=[names.get(row['task_id'],'Задача'),'', 'Состояние: '+states.get(row['status'],row['status']),f"Попыток: {row['attempts']}"]
        for field,title in [('scheduled_at','Назначено'),('started','Начало'),('finished','Завершение'),('retry_at','Повтор')]:
            if row.get(field):lines.append(title+': '+store.display_time(row[field]).strftime('%d.%m.%Y %H:%M:%S'))
        if row.get('summary'):lines+=['','Результат: '+row['summary']]
        if row.get('error'):lines+=['','Ошибка: '+row['error']]
        text=QTextBrowser(); text.setPlainText('\n'.join(lines)); box.addWidget(text)
        box.addWidget(btn('Закрыть',win.close)); win.show()

    def show_task_log(self,task):
        win=self.dialog('История · '+task['name']); box=QVBoxLayout(win)
        text=QTextBrowser()
        rows=store.runs(task['id'],50)
        text.setPlainText('\n\n'.join(f"{store.display_time(r['scheduled_at']):%d.%m %H:%M} · {r['status']} · попыток {r['attempts']}\n{r['summary'] or ''}\n{r['error'] or ''}" for r in rows) or 'Запусков ещё нет.')
        box.addWidget(text); box.addWidget(btn('Закрыть',win.close)); win.show()

    def edit_task(self,task=None,day_offset=0):
        if isinstance(task,bool):task=None
        now=datetime.now(self.display_zone)
        default=(now+timedelta(days=day_offset)).replace(hour=9,minute=0,second=0,microsecond=0) if day_offset else now+timedelta(hours=1)
        task=deepcopy(task) if task else new_task('Новое напоминание','reminder',{'type':'once','at':default.isoformat(),'timezone':store.timezone_name()})
        win=self.dialog('Настройка автоматизации',600); win.resize(600,min(700,self.screen().availableGeometry().height()-60))
        root=QVBoxLayout(win);scroll=QScrollArea();scroll.setObjectName('taskEditorScroll');scroll.setWidgetResizable(True)
        content=QWidget();layout=QVBoxLayout(content);layout.setContentsMargins(4,4,12,4);form=QFormLayout();form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        scroll.setWidget(content);root.addWidget(scroll,1)
        name=QLineEdit(task['name']); form.addRow('Название',name)
        body=QTextEdit(task['config'].get('body','')); body.setFixedHeight(85)
        if task['kind']=='reminder' and not task['config'].get('project_id'):form.addRow('Текст',body)
        elif task['config'].get('project_id'):form.addRow(label('Текст берётся из следующего шага связанного проекта.',12))
        repeat=QComboBox(); repeat.addItems(['Один раз','Каждый день','По выбранным дням','Еженедельно'])
        spec=task['schedule']; index=0 if spec['type']=='once' else 3 if spec['type']=='weekly' else 1 if spec.get('days')==list(range(7)) else 2
        zone=QComboBox();zone.setEditable(True);zone.addItems(sorted(available_timezones()));zone.setCurrentText(spec.get('timezone','Asia/Yekaterinburg'));form.addRow('Часовой пояс задачи',zone)
        zone.setEnabled(task['kind']!='weather')
        repeat.setCurrentIndex(index); form.addRow('Повторение',repeat)
        at=parse_time(spec['at']).astimezone(ZoneInfo(zone.currentText())) if spec['type']=='once' else now.astimezone(ZoneInfo(zone.currentText()))+timedelta(hours=1)
        date=QDateTimeEdit(QDateTime.fromString(at.strftime('%Y-%m-%d %H:%M'),'yyyy-MM-dd HH:mm'))
        date.setDisplayFormat('dd.MM.yyyy HH:mm'); date.setCalendarPopup(True); form.addRow('Дата и время',date)
        clock=QTimeEdit(QTime.fromString(spec.get('time','19:00'),'HH:mm')); clock.setDisplayFormat('HH:mm'); form.addRow('Время',clock)
        days_widget=QWidget(); days_box=QHBoxLayout(days_widget); days_box.setContentsMargins(0,0,0,0); days=[]
        for d,text in enumerate(['Пн','Вт','Ср','Чт','Пт','Сб','Вс']):
            check=QCheckBox(text); check.setChecked(d in spec.get('days',[0,1,2,3,4])); days_box.addWidget(check); days.append(check)
        form.addRow('Дни',days_widget)
        week=QComboBox(); week.addItems(['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье'])
        week.setCurrentIndex(spec.get('days',[4])[0]); form.addRow('День недели',week)
        policy=QComboBox(); policy.addItems(['Выполнить последний пропущенный запуск','Пропустить после срока актуальности'])
        policy.setCurrentIndex(1 if task['policy']=='skip' else 0); form.addRow('После сна / простоя',policy)
        grace=QSpinBox(); grace.setRange(1,525600); grace.setValue(max(1,task['grace_seconds']//60)); grace.setSuffix(' мин'); form.addRow('Срок актуальности',grace)
        attempts=QSpinBox(); attempts.setRange(1,5); attempts.setValue(task['max_attempts']); form.addRow('Максимум попыток',attempts)
        retry=QSpinBox(); retry.setRange(1,1440); retry.setValue(max(1,task['retry_seconds']//60)); retry.setSuffix(' мин'); form.addRow('Между попытками',retry)
        enabled=QCheckBox('Включить автоматизацию'); enabled.setChecked(task['enabled']); form.addRow(enabled)
        layout.addLayout(form)
        hint=label('Новые задачи сохраняются выключенными, пока ты их не включишь. Ручной запуск доступен и для выключенной задачи.',12); hint.setWordWrap(True); layout.addWidget(hint)
        def update_fields():
            value=repeat.currentIndex()
            form.setRowVisible(date,value==0);form.setRowVisible(clock,value!=0)
            form.setRowVisible(days_widget,value==2);form.setRowVisible(week,value==3)
            form.setRowVisible(grace,policy.currentIndex()==1)
        repeat.currentIndexChanged.connect(update_fields); policy.currentIndexChanged.connect(update_fields); update_fields()
        def save():
            try:
                value=repeat.currentIndex()
                if value==0:
                    from automation_models import wall_time
                    wall=datetime.strptime(date.dateTime().toString('yyyy-MM-dd HH:mm'),'%Y-%m-%d %H:%M')
                    selected=wall_time(wall.date(),wall.strftime('%H:%M'),ZoneInfo(zone.currentText()))
                    if selected is None:raise ValueError('Этот час отсутствует из-за перехода времени. Выбери другое время.')
                    if selected<datetime.now(store.LOCAL)-timedelta(minutes=1):raise ValueError('Выбери будущую дату и время.')
                    schedule={'type':'once','at':selected.isoformat()}
                else:
                    schedule={'type':'weekly' if value==3 else 'daily','time':clock.time().toString('HH:mm'),
                              'days':[week.currentIndex()] if value==3 else list(range(7)) if value==1 else [i for i,c in enumerate(days) if c.isChecked()]}
                schedule['timezone']=zone.currentText()
                if task['kind']=='weather' and enabled.isChecked() and not locations.current():raise ValueError('Сначала выбери место для погоды.')
                task.update(name=name.text().strip(),schedule=schedule,enabled=enabled.isChecked(),
                            policy='skip' if policy.currentIndex()==1 else 'latest',grace_seconds=grace.value()*60,
                            max_attempts=attempts.value(),retry_seconds=retry.value()*60)
                if not task['config'].get('project_id'):task['config']['body']=body.toPlainText().strip()
                store.save_task(task); win.close(); self.tick()
            except (ValueError,KeyError) as exc:QMessageBox.warning(win,'Проверь настройки',str(exc))
        layout.addStretch();actions=QHBoxLayout();actions.addWidget(btn('Отмена',win.close))
        save_button=btn('Сохранить',save,True);save_button.setDefault(True);actions.addWidget(save_button);root.addLayout(actions);win.show()

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and event.position().y()<90:
            self.windowHandle().startSystemMove()

    def toggle_pin(self):
        self.pinned=not self.pinned
        store.set_setting('topmost',self.pinned)
        self.setWindowFlag(Qt.WindowStaysOnTopHint,self.pinned)
        self.pin.setText('Закреплено' if self.pinned else 'Поверх окон')
        self.show()

    def set_filter(self,name):
        self.filter=name; self.fingerprint=None
        for title,b in self.filter_buttons.items():
            b.setProperty('active',title==name); b.style().unpolish(b); b.style().polish(b)
        self.redraw()

    def redraw(self):
        self.feed_dirty=False
        rows=store.user_events()
        fingerprint=(self.filter,tuple((r['id'],r['seen'],r['title'],r['body'],r['created'],r.get('target'),r.get('action_state')) for r in rows))
        if fingerprint==self.fingerprint:return
        self.fingerprint=fingerprint
        while self.feed.count():
            item=self.feed.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        selected=[r for r in rows if self.filter=='Все' or r['category']==self.filter]
        if not selected:
            empty=label('Здесь появятся результаты твоих автоматизаций.',13)
            self.feed.addWidget(empty)
        for row in selected:
            card=GlassCard('#39485e'); layout=QVBoxLayout(card); layout.setContentsMargins(18,15,18,15)
            timestamp=parse_time(row['created']).astimezone(self.display_zone).strftime('%d.%m · %H:%M')
            layout.addWidget(label(f"{'●  ' if not row['seen'] else ''}{row['category']}  /  {timestamp}",11,'#a4e4d2' if not row['seen'] else '#9eabc2'))
            title=label(row['title'],15,'#f0f4ff',True); title.setWordWrap(True); layout.addWidget(title)
            excerpt=label(row['body'][:165].replace('\n',' ')+('…' if len(row['body'])>165 else ''),12)
            excerpt.setWordWrap(True); layout.addWidget(excerpt)
            actions=QHBoxLayout(); actions.addWidget(btn('Открыть занятие' if (row.get('target') or '').startswith('lesson:') else 'Открыть',lambda checked=False,r=row:self.open_event(r))); actions.addStretch(); layout.addLayout(actions)
            self.feed.addWidget(card)

    def dialog(self,title,width=580):
        win=QDialog(self); win.setWindowTitle(title); win.setStyleSheet(STYLE+'QDialog {background:#1c273c;}')
        win.setAttribute(Qt.WA_DeleteOnClose)
        win.resize(width,460); return win

    def open_event(self,row):
        store.mark_seen(row['id']); self.redraw()
        target=row.get('target') or ''
        if target=='course:db2':
            self.reveal(); self.switch_page(3); return
        if target.startswith('lesson:db2:'):
            try:
                self.open_learning(target.split(':',2)[2]); return
            except ValueError:pass
        if target.startswith('project:'):
            try:
                key=target.split(':',1)[1];self.open_project(key)
                self.project_dialogs[key].show_notification(row);return
            except ValueError:pass
        win=self.dialog(row['title']); layout=QVBoxLayout(win); layout.setContentsMargins(22,22,22,22)
        title=label(row['title'],20,'#eef4ff',True); title.setWordWrap(True); layout.addWidget(title)
        text=QTextBrowser(); text.setPlainText(row['body']); layout.addWidget(text)
        if row.get('action_state') in ('pending','snoozed'):
            actions=QHBoxLayout()
            def act(action):
                store.reminder_action(row['id'],action); win.close(); self.tick()
            actions.addWidget(btn('Выполнено',lambda:act('done'),True))
            actions.addWidget(btn('Отложить на 15 минут',lambda:act('snooze')))
            layout.addLayout(actions)
        elif row.get('action_state')=='done':layout.addWidget(label('✓ Выполнено',13,'#a3eed8'))
        elif row.get('action_state')=='cancelled':layout.addWidget(label('Напоминание отменено',13))
        layout.addWidget(btn('Закрыть',win.close)); win.show()

    def open_learning(self,lesson_id):
        import learning_service as learning
        learning.lesson(lesson_id)
        self.reveal(); self.switch_page(3)
        dialog=self.learning_dialogs.get(lesson_id)
        if dialog is not None:
            dialog.showNormal(); dialog.raise_(); dialog.activateWindow(); return
        dialog=LessonDialog(self,lesson_id); self.learning_dialogs[lesson_id]=dialog
        dialog.destroyed.connect(lambda obj=None,key=lesson_id:self.learning_dialogs.pop(key,None))
        dialog.show(); self.learning_page.refresh()

    def open_project(self,project_id):
        import project_service as projects
        projects.get(project_id)
        self.reveal();self.switch_page(4)
        dialog=self.project_dialogs.get(project_id)
        if dialog is not None:
            dialog.showNormal();dialog.raise_();dialog.activateWindow();return
        dialog=ProjectDialog(self,project_id);self.project_dialogs[project_id]=dialog
        dialog.destroyed.connect(lambda obj=None,key=project_id:self.project_dialogs.pop(key,None))
        dialog.show()

    def read_all(self):
        store.mark_seen(); self.redraw()

    def open_folder(self,path):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):QMessageBox.information(self,'Не удалось открыть папку',str(path))

    def help(self):
        path=docs_dir()/'USER_GUIDE.md'
        if not path.exists():path=docs_dir()/'MANUAL.md'
        if not path.exists():path=program_dir()/'MANUAL.md'
        win=self.dialog('Руководство Орбиты',820);win.resize(820,min(760,self.screen().availableGeometry().height()-60));box=QVBoxLayout(win)
        text=QTextBrowser();text.setOpenExternalLinks(True)
        text.document().setBaseUrl(QUrl.fromLocalFile(path.parent.as_posix()+'/'))
        try:text.setMarkdown(path.read_text(encoding='utf-8'))
        except OSError:text.setPlainText('Руководство не найдено. Папка документации: '+str(docs_dir()))
        box.addWidget(text);box.addWidget(btn('Закрыть',win.close));win.show()

    def about(self):
        win=self.dialog('Об Орбите',530);box=QVBoxLayout(win)
        box.addWidget(label('Орбита '+VERSION,25,'#c3f5e5',True))
        text=label('Личные автоматизации, проекты и обучение. Данные сохраняются на этом устройстве.',14);text.setWordWrap(True);box.addWidget(text)
        box.addWidget(btn('Руководство',self.help));box.addWidget(btn('Папка программы',lambda:self.open_folder(program_dir())))
        box.addWidget(btn('Документы приложения',lambda:self.open_folder(docs_dir())))
        legal=label('Код Орбиты: MIT. Qt / PySide6 / Shiboken: LGPLv3. Условия сторонних компонентов и исходники библиотек доступны в документации.',12)
        legal.setWordWrap(True);box.addWidget(legal)
        box.addWidget(btn('Лицензии и исходники библиотек',lambda:self.open_folder(program_dir()/'licenses')))
        box.addStretch();box.addWidget(btn('Закрыть',win.close));win.show()

    def settings(self):
        win=self.dialog('Настройки Орбиты',570); layout=QVBoxLayout(win); layout.setContentsMargins(25,25,25,25)
        layout.addWidget(label('Настройки',24,'#f1f6ff',True))
        layout.addWidget(btn('Местоположение и часы погоды',self.configure_location))
        zone=QComboBox();zone.setObjectName('profileTimezone');zone.setEditable(True);zone.addItems(sorted(available_timezones()));zone.setCurrentText(store.timezone_name())
        zone.setEnabled(not bool(self.location_profile));layout.addWidget(zone)
        zone.setToolTip('Без выбранного места используется этот пояс. При настройке погоды — пояс выбранного места. Существующие задачи сохраняют свой пояс.')
        startup=QCheckBox('Запускать при входе в Windows'); startup.setChecked(windows_integration.autostart_enabled()); layout.addWidget(startup)
        startup.setVisible(sys.platform=='win32')
        toasts=QCheckBox('Всплывающие уведомления'); toasts.setChecked(store.get_setting('toasts',True)); layout.addWidget(toasts)
        motion=QCheckBox('Анимации погоды');motion.setObjectName('weatherAnimations');motion.setChecked(store.get_setting('animations',True));layout.addWidget(motion)
        motion.setToolTip('Выключи для статичных иллюстраций и меньшей нагрузки. Автоматизации продолжат работать.')
        dnd=QCheckBox('Не беспокоить'); dnd.setChecked(store.get_setting('dnd',False)); layout.addWidget(dnd)
        quiet=QCheckBox('Тихие часы'); quiet.setChecked(store.get_setting('quiet_enabled',False)); layout.addWidget(quiet)
        form=QFormLayout(); start=QTimeEdit(QTime.fromString(store.get_setting('quiet_start','22:00'),'HH:mm'))
        end=QTimeEdit(QTime.fromString(store.get_setting('quiet_end','08:00'),'HH:mm'))
        start.setDisplayFormat('HH:mm'); end.setDisplayFormat('HH:mm')
        form.addRow('Начало · '+store.timezone_name(),start); form.addRow('Конец · '+store.timezone_name(),end)
        def quiet_fields():
            form.setRowVisible(start,quiet.isChecked());form.setRowVisible(end,quiet.isChecked())
        quiet.toggled.connect(quiet_fields);quiet_fields()
        seconds=QSpinBox(); seconds.setRange(3,60); seconds.setValue(store.get_setting('toast_seconds',13)); seconds.setSuffix(' сек')
        form.addRow('Длительность уведомления',seconds); layout.addLayout(form)
        note=label('«Не беспокоить» и тихие часы откладывают показ уведомлений. Задачи продолжают выполняться, результаты остаются в ленте.',12)
        note.setWordWrap(True); layout.addWidget(note); layout.addStretch()
        def save():
            try:
                if startup.isChecked()!=windows_integration.autostart_enabled():windows_integration.set_autostart(startup.isChecked())
                if not self.location_profile:preferences.set_timezone(zone.currentText())
                for key,value in {'toasts':toasts.isChecked(),'animations':motion.isChecked(),'dnd':dnd.isChecked(),'quiet_enabled':quiet.isChecked(),
                                  'quiet_start':start.time().toString('HH:mm'),'quiet_end':end.time().toString('HH:mm'),
                                  'toast_seconds':seconds.value()}.items():store.set_setting(key,value)
                win.close(); self.tick()
            except (OSError,ValueError,KeyError) as exc:QMessageBox.warning(win,'Настройки не сохранены',str(exc))
        layout.addWidget(btn('Сохранить',save,True)); win.show()

    def apply_snapshot(self,snapshot):
        if hasattr(self,'weather_status'):status=self.weather_status
        else:
            latest=store.runs('weather',1);status=latest[0]['status'] if latest else None
        now=datetime.now(self.display_zone)
        for panel in (self.weather_panel,self.tomorrow_page.weather):
            panel.render(self.location_profile,self.display_zone,self.weather_hours,self.saved_forecasts,snapshot,now,status)

    def fetch_weather(self,checked=False,scheduled=False):
        if not locations.current():self.configure_location();return
        self.engine.run_now('weather'); self.tick()

    def tick(self):
        now=datetime.now(self.display_zone)
        visible=self.isVisible() and not self.isMinimized()
        self.timer.setInterval(1300 if visible else 3500)
        revision=self.revision_reader.value()
        changed=revision!=self.last_revision
        if changed:
            self.last_revision=revision
            self.has_pending=True;self.feed_dirty=True;self.visual_dirty=True
            settings=store.get_settings()
            self.location_profile=settings.get('location_profile');self.display_zone=ZoneInfo(timezone_from_settings(settings))
            self.weather_hours=settings.get('weather_hours',[9,13,17])
            now=datetime.now(self.display_zone)
            self.settings_cache={key:settings.get(key,default) for key,default in
                [('toasts',True),('dnd',False),('quiet_enabled',False),('quiet_start','22:00'),('quiet_end','08:00'),('paused',False)]}
            self.settings_cache['timezone']=str(self.display_zone)
            task=next(t for t in store.tasks() if t['id']=='weather')
            self.schedule.setText(('●  '+schedule_text(task)) if task['enabled'] else '○  Погода по запросу · расписание выключено')
            self.saved_snapshot=settings.get('weather_snapshot')
            self.saved_forecasts=settings.get('weather_forecasts',{})
            latest=store.runs('weather',1); busy=bool(latest and latest[0]['status']=='running')
            self.weather_status=latest[0]['status'] if latest else None
            self.weather_panel.set_busy(busy,bool(self.location_profile));self.tomorrow_page.weather.set_busy(busy,bool(self.location_profile))
            paused=self.settings_cache['paused']
            self.pause_action.setText('Продолжить автоматизации' if paused else 'Приостановить автоматизации')
            self.quiet_action.setChecked(self.settings_cache['dnd'])
            for art in self.findChildren(WeatherArt):art.set_motion(settings.get('animations',True))
            for dialog in self.project_dialogs.values():dialog.refresh_reminder()
            if self.weather_refresh_pending and not busy:
                self.weather_refresh_pending=False;self.engine.run_now('weather')
        minute=now.strftime('%Y-%m-%d-%H-%M')
        if visible:
            dirty=self.visual_dirty
            if dirty:
                if self.pages.currentIndex()==1:self.redraw_tasks()
                if self.pages.currentIndex()==2:self.redraw_logs()
                if self.pages.currentIndex()==3:self.learning_page.refresh()
                if self.pages.currentIndex()==4:self.projects_page.refresh()
            if self.pages.currentIndex()==0:
                if self.feed_dirty:self.redraw()
                if dirty or self.today_minute!=minute:self.refresh_today()
            if self.pages.currentIndex()==5 and (dirty or self.tomorrow_minute!=minute):self.refresh_tomorrow()
            if dirty or self.snapshot_minute!=minute:
                place=self.location_profile['name'] if self.location_profile else 'Место не выбрано'
                self.clock.setText(f'{now:%d.%m.%Y}  ·  {now:%H:%M}  /  {place} · {self.display_zone}')
                self.clock.setWordWrap(True)
                self.snapshot_minute=minute;self.apply_snapshot(self.saved_snapshot)
            self.visual_dirty=False
        quiet=quiet_now(self.settings_cache,now)
        if quiet or not self.settings_cache.get('toasts',True):
            for toast in self.toasts:toast.close()
        self.toasts=[toast for toast in self.toasts if toast.isVisible()]
        if self.has_pending and not self.toasts and not quiet and self.settings_cache.get('toasts',True):
            pending=store.pending_events(1)
            if pending:
                self.toasts.append(Toast(pending[0],self)); store.delivered(pending[0]['id'])
            else:self.has_pending=False
        paused=self.settings_cache.get('paused',False)
        self.status.setText('●  Автоматизации на паузе' if paused else '●  Не беспокоить · задачи работают' if quiet else '●  Автоматизации работают')

    def save_geometry(self):
        if not self.isMinimized():store.set_setting('window_geometry',[self.x(),self.y(),self.width(),self.height()])

    def quit_app(self):
        if self.quitting:return
        for dialog in list(self.learning_dialogs.values())+list(self.project_dialogs.values()):
            if not dialog.flush():
                self.reveal(); dialog.showNormal(); dialog.raise_(); dialog.activateWindow()
                return
        self.quitting=True; self.save_geometry(); self.timer.stop(); self.tray.hide()
        self.location_refresher.cancel()
        for toast in self.toasts:toast.close()
        self.hide()
        for dialog in self.findChildren(QDialog):dialog.close()
        self.shutdown_thread=threading.Thread(target=self.engine.stop,daemon=True); self.shutdown_thread.start()
        self.shutdown_poll=QTimer(self)
        def check():
            if not self.shutdown_thread.is_alive():
                self.shutdown_poll.stop(); self.revision_reader.close(); QApplication.instance().quit()
        self.shutdown_poll.timeout.connect(check); self.shutdown_poll.start(100)

    def closeEvent(self,event):
        self.save_geometry()
        if self.quitting:event.accept(); return
        if QSystemTrayIcon.isSystemTrayAvailable():self.hide()
        else:self.showMinimized()
        event.ignore()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--publish-file')
    parser.add_argument('--smoke-test',action='store_true')
    parser.add_argument('--capture')
    parser.add_argument('--background',action='store_true')
    parser.add_argument('--learning',action='store_true',help='Open the learning overview')
    parser.add_argument('--projects',action='store_true',help='Open the projects overview')
    parser.add_argument('--tomorrow',action='store_true',help='Open the next-day overview')
    parser.add_argument('--open-project',help='Open a local project by its stable identifier')
    parser.add_argument('--open-lesson',help='Open an IBM Db2 lesson by its stable identifier')
    parser.add_argument('--location-setup',action='store_true',help='Open location configuration')
    parser.add_argument('--welcome',action='store_true',help='Open the optional first-run guide')
    parser.add_argument('--verify-corners',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.verify_corners:
        from verify_window_corners import verify
        verify(args.verify_corners,strict=True)
        return
    if args.open_lesson:
        from db2_content import BY_ID
        if args.open_lesson not in BY_ID:parser.error('Unknown IBM Db2 lesson')
    if args.publish_file:
        payload=json.loads(Path(args.publish_file).read_text(encoding='utf-8-sig'))
        store.publish(payload['title'],payload['body'],payload.get('category','Задачи'),payload.get('dedupe'))
        return
    mutex=None
    if sys.platform=='win32':
        ctypes.windll.kernel32.CreateMutexW.restype=ctypes.c_void_p
        mutex=ctypes.windll.kernel32.CreateMutexW(None,False,windows_integration.instance_name(store.HOME))
        if ctypes.windll.kernel32.GetLastError()==183:
            if not args.background:
                handle=ctypes.windll.user32.FindWindowW(None,'Орбита · Glass')
                if handle:
                    ctypes.windll.user32.ShowWindow(handle,9); ctypes.windll.user32.SetForegroundWindow(handle)
            return
    app=QApplication(sys.argv[:1]);app.setApplicationName('Orbita');app.setApplicationVersion(VERSION);app.setOrganizationName('Orbita');install_theme(app)
    app.setQuitOnLastWindowClosed(False)
    store.initialize()
    logging.basicConfig(filename=store.HOME/'orbita.log',level=logging.WARNING,
                        format='%(asctime)s %(levelname)s %(message)s')
    window=Window()
    if not args.background or not QSystemTrayIcon.isSystemTrayAvailable():window.show()
    if args.learning:window.switch_page(3)
    if args.projects:window.switch_page(4)
    if args.tomorrow:window.switch_page(5)
    if args.open_lesson:window.open_learning(args.open_lesson)
    if args.open_project:
        try:window.open_project(args.open_project)
        except ValueError:window.switch_page(4)
    window.location_prompt_on_reveal=args.background
    if args.welcome:QTimer.singleShot(100,window.show_welcome)
    elif args.location_setup:QTimer.singleShot(100,window.configure_location)
    elif not args.background and not args.capture and not args.smoke_test:QTimer.singleShot(350,window.offer_location_setup)
    if args.smoke_test:
        QTimer.singleShot(7000,window.quit_app)
    if args.capture:
        def capture():
            target=window.welcome_dialog or window.location_dialog or window.project_dialogs.get(args.open_project) or window.learning_dialogs.get(args.open_lesson,window)
            target.grab().save(args.capture)
            window.quit_app()
        QTimer.singleShot(6500,capture)
    app.exec()
    if mutex:ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mutex))


if __name__=='__main__':main()
