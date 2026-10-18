"""Qt course views. All persistence and selection logic live in learning_service."""
from datetime import datetime
import html
import sqlite3

from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QTabWidget,QTextBrowser,QPlainTextEdit,QScrollArea,QComboBox,QLineEdit,QFormLayout,
    QFileDialog,QMessageBox)

import desktop_store as store
import learning_service as learning
from ui_components import GlassCard,label,btn,SaveGuardDialog
from ui_theme import STYLE
from db2_content import (LESSONS,BY_ID,TOPICS,SOURCES,COMPATIBILITY,SETUP_GUIDE,
                         CONTENT_VERSION,expected_text,dataset_text,fixture_sql)


def plain(text='',editable=False):
    widget=QPlainTextEdit()
    widget.setPlainText(text); widget.setReadOnly(not editable)
    widget.setFont(QFont('Consolas',11)); widget.setTabStopDistance(widget.fontMetrics().horizontalAdvance(' ')*4)
    widget.setStyleSheet('QPlainTextEdit {background:rgba(14,24,39,190); color:#e1eafb; border:1px solid #41516c; border-radius:12px; padding:12px;}')
    return widget


def text_view(text):
    widget=QTextBrowser(); widget.setPlainText(text); return widget


class LearningPage(QWidget):
    def __init__(self,owner):
        super().__init__()
        self.owner=owner; self.fingerprint=None
        self.setObjectName('learningContent'); self.setStyleSheet('#learningContent {background:transparent;}')
        self.layout=QVBoxLayout(self); self.layout.setContentsMargins(0,2,6,10); self.layout.setSpacing(12)

    def refresh(self):
        records=learning.overview(); profile=learning.profile()
        fingerprint=(tuple((key,record['state'],record['assessment']) for key,record in sorted(records.items())),
                     profile['active_lesson'],profile['platform'],profile['server_version'])
        if fingerprint==self.fingerprint:return
        self.fingerprint=fingerprint
        while self.layout.count():
            item=self.layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.layout.addWidget(label('Обучение',24,'#f0f5ff',True))
        intro=GlassCard('#3d5069'); box=QVBoxLayout(intro); box.setContentsMargins(18,18,18,18)
        box.addWidget(label('IBM Db2 · практика для администратора',18,'#eaf4ff',True))
        done=sum(records.get(item['id'],{}).get('state')=='completed_user' for item in LESSONS if item['id']!='diagnostic')
        diagnostic_done=records.get('diagnostic',{}).get('state')=='completed_user'
        line=label(f"Занятий завершено тобой: {done}/6 · диагностика {'завершена' if diagnostic_done else 'не завершена'}",12)
        line.setWordWrap(True); box.addWidget(line)
        note=label('Самостоятельная практика на вымышленном архиве. Отметка о завершении — твоя, правильность SQL приложение не подтверждает.',12)
        note.setWordWrap(True); box.addWidget(note)
        context=label('Среда: '+(profile['platform'] or 'платформа не указана')+' · '+(profile['server_version'] or 'версия не указана'),11)
        context.setWordWrap(True); box.addWidget(context)
        actions=QHBoxLayout(); current=learning.current_lesson()
        if current:actions.addWidget(btn('Продолжить' if records.get(current['id'],{}).get('state')=='in_progress' else 'Начать диагностику' if current['id']=='diagnostic' else 'Следующее занятие',
                                        lambda checked=False,item=current:self.owner.open_learning(item['id']),True))
        actions.addWidget(btn('Моя Db2',self.environment)); box.addLayout(actions)
        self.layout.addWidget(intro)
        order=learning.recommended_order()
        sequence=' → '.join(BY_ID[key]['title'].split('. ',1)[0] for key in order)
        plan=label(('Рекомендуемый порядок: '+sequence if order else 'Стартовый набор завершён пользователем.')+
                   ('\nПорядок учитывает твою самооценку и зависимости тем.' if diagnostic_done else '\nПосле диагностики отметь пробелы — порядок будет уточнён.'),12)
        plan.setWordWrap(True); self.layout.addWidget(plan)
        for item in LESSONS:
            row=records.get(item['id'],{}); state=row.get('state','not_started')
            card=GlassCard('#35485e'); content=QVBoxLayout(card); content.setContentsMargins(18,14,18,14)
            title=label(item['title'],15,'#f1f5ff',True); title.setWordWrap(True); content.addWidget(title)
            content.addWidget(label(learning.STATES[state]+' · '+item['minutes']+' минут',11,'#a3eed8' if state=='completed_user' else '#a9b6cd'))
            goal=label(item['goal'],12); goal.setWordWrap(True); content.addWidget(goal)
            content.addWidget(btn('Открыть' if state=='not_started' else 'Продолжить' if state=='in_progress' else 'Повторить материал',
                                  lambda checked=False,key=item['id']:self.owner.open_learning(key)))
            self.layout.addWidget(card)
        self.layout.addWidget(label('Материалы '+CONTENT_VERSION+' · диагностическая оценка не автоматическая',11))
        self.layout.addStretch()

    def environment(self):
        win=self.owner.dialog('Моя среда Db2',520); box=QVBoxLayout(win); form=QFormLayout()
        profile=learning.profile()
        platform=QComboBox(); platform.addItems(['Не указана','LUW','z/OS','IBM i']); platform.setCurrentText(profile['platform'] or 'Не указана')
        version=QLineEdit(profile['server_version']); version.setPlaceholderText('Например: версия из сведений о сервере')
        form.addRow('Платформа сервера',platform); form.addRow('Версия / уровень',version); box.addLayout(form)
        note=label('Не определяй платформу по DBeaver: это клиент для разных СУБД. Эти сведения только сохраняются и включаются в вопрос для Codex; приложение не проверяет сервер.',12)
        note.setWordWrap(True); box.addWidget(note)
        def save():
            learning.set_profile(platform='' if platform.currentIndex()==0 else platform.currentText(),server_version=version.text().strip())
            win.close(); self.refresh()
        box.addWidget(btn('Сохранить',save,True)); win.show()


class LessonDialog(SaveGuardDialog):
    def __init__(self,owner,lesson_id):
        super().__init__(owner)
        self.owner=owner; self.lesson_id=lesson_id; self.item=learning.lesson(lesson_id)
        self.dirty=False; self.solution_visible=False
        learning.start(lesson_id); self.record=learning.progress(lesson_id)
        self.setWindowTitle(self.item['title']); self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet(STYLE+'QDialog {background:#1c273c;}')
        area=owner.screen().availableGeometry(); self.resize(min(940,area.width()-50),min(850,area.height()-55))
        root=QVBoxLayout(self); root.setContentsMargins(20,18,20,18); root.setSpacing(10)
        heading=label(self.item['title'],20,'#edf5ff',True); heading.setWordWrap(True); root.addWidget(heading)
        self.state_label=label('',12); root.addWidget(self.state_label)
        self.tabs=QTabWidget(); self.tabs.setStyleSheet('QTabWidget::pane {border:none;} QTabBar::tab {background:#26344b; padding:10px 14px; border-radius:8px; margin-right:3px;} QTabBar::tab:selected {background:#3b5963; color:#c9f8eb;}')
        root.addWidget(self.tabs,1)
        assignment='ЦЕЛЬ\n'+self.item['goal']+'\n\nКРАТКО\n'+self.item['explanation']+'\n\nЗАДАНИЕ\n'+self.item['task']+'\n\n'+SETUP_GUIDE
        self.tabs.addTab(text_view(assignment),'Задание')
        answer_page=QWidget(); answer_box=QVBoxLayout(answer_page); answer_box.setContentsMargins(0,8,0,0)
        answer_box.addWidget(label('SQL сохраняется как текст и не выполняется.',12))
        self.answer=plain(self.record['answer'],True); self.answer.setPlaceholderText('-- Напиши запрос и рассуждение. Для диагностики отметь пункты A–D.')
        self.answer.setObjectName('learningAnswer'); answer_box.addWidget(self.answer,3)
        answer_box.addWidget(label('Заметки, наблюдения и результат ручного запуска',12))
        self.notes=plain(self.record['notes'],True); self.notes.setObjectName('learningNotes'); answer_box.addWidget(self.notes,1)
        self.tabs.addTab(answer_page,'Мой ответ')
        data_page=QWidget(); data_box=QVBoxLayout(data_page); data_box.setContentsMargins(0,8,0,0)
        data_tabs=QTabWidget(); data_tabs.addTab(plain(dataset_text()),'Таблицы и строки'); data_tabs.addTab(plain(fixture_sql()),'SQL-скрипт данных')
        data_box.addWidget(data_tabs)
        data_actions=QHBoxLayout(); data_actions.addWidget(btn('Скопировать скрипт',lambda:QApplication_clipboard(fixture_sql())))
        data_actions.addWidget(btn('Сохранить .sql',self.export)); data_box.addLayout(data_actions)
        self.tabs.addTab(data_page,'Данные')
        self.check_page=QWidget(); check_box=QVBoxLayout(self.check_page); check_box.setContentsMargins(0,8,0,0)
        check_box.addWidget(label('Ожидаемые строки · сравни результат самостоятельно',13,'#eaf4ff',True))
        expected=plain(expected_text(self.item)); expected.setMaximumHeight(190); check_box.addWidget(expected)
        checks=text_view('КРИТЕРИИ\n'+'\n'.join('• '+value for value in self.item['checks'])); checks.setMaximumHeight(140); check_box.addWidget(checks)
        self.hints=plain(); self.hints.setMaximumHeight(150); check_box.addWidget(self.hints)
        self.hint_button=btn('Следующая подсказка',self.hint); check_box.addWidget(self.hint_button)
        self.solution_button=btn('Показать эталон'+(' (открывался раньше)' if self.record['solution_revealed'] else ''),self.solution)
        check_box.addWidget(self.solution_button)
        self.solution_view=plain(); self.solution_view.setObjectName('learningSolution'); self.solution_view.hide(); check_box.addWidget(self.solution_view,1)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(self.check_page)
        self.tabs.addTab(scroll,'Самопроверка')
        self.assessment_boxes={}
        if lesson_id=='diagnostic':
            assessment_page=QWidget(); assessment_box=QVBoxLayout(assessment_page)
            message=label('После сравнения со справочным решением отметь темы. Это твоя самооценка; SQL здесь автоматически не проверяется.',13)
            message.setWordWrap(True); assessment_box.addWidget(message)
            form=QFormLayout()
            for key,title in TOPICS.items():
                combo=QComboBox()
                for value,name in learning.LEVELS.items():combo.addItem(name,value)
                combo.setCurrentIndex(combo.findData(self.record['assessment'].get(key,'unknown')))
                self.assessment_boxes[key]=combo; form.addRow(title,combo)
            assessment_box.addLayout(form); assessment_box.addStretch(); self.tabs.addTab(assessment_page,'Самооценка')
        sources=text_view(COMPATIBILITY)
        source_html='<p>'+html.escape(COMPATIBILITY)+'</p><p>Официальные источники IBM:</p><ul>'
        for key in dict.fromkeys(['platform']+self.item['sources']):
            name,url=SOURCES[key]; source_html+='<li><a href="'+html.escape(url,quote=True)+'">'+html.escape(name)+'</a></li>'
        source_html+='</ul><p>Документация описывает указанные версии, а не неизвестную конфигурацию твоего сервера. Примеры и данные курса разработаны для Орбиты.</p>'
        sources.setHtml(source_html); sources.setOpenExternalLinks(True); self.tabs.addTab(sources,'Среда и источники')
        bottom=QHBoxLayout(); self.saved=label('Ответ и заметки сохраняются автоматически',11); bottom.addWidget(self.saved); bottom.addStretch()
        bottom.addWidget(btn('Сохранить',self.flush)); root.addLayout(bottom)
        actions=QHBoxLayout(); actions.addWidget(btn('Вопрос для Codex',self.question))
        self.complete_button=btn('',self.toggle_complete,True); actions.addWidget(self.complete_button)
        actions.addWidget(btn('Следующее',self.next_lesson)); actions.addWidget(btn('Закрыть',self.close)); root.addLayout(actions)
        self.debounce=QTimer(self); self.debounce.setSingleShot(True); self.debounce.timeout.connect(self.flush)
        self.answer.textChanged.connect(self.changed); self.notes.textChanged.connect(self.changed)
        for combo in self.assessment_boxes.values():combo.currentIndexChanged.connect(self.changed)
        self.update_state(); self.update_hints()

    def changed(self):
        self.dirty=True; self.saved.setText('Есть изменения…'); self.debounce.start(650)

    def flush(self):
        if not self.dirty:return True
        try:
            changes={'answer':self.answer.toPlainText(),'notes':self.notes.toPlainText()}
            if self.assessment_boxes:changes['assessment']={key:combo.currentData() for key,combo in self.assessment_boxes.items()}
            learning.save_progress(self.lesson_id,**changes)
            self.record=learning.progress(self.lesson_id); self.dirty=False; self.debounce.stop()
            self.saved.setText('Сохранено '+datetime.now(store.LOCAL).strftime('%H:%M:%S')+' · SQL не проверен')
            return True
        except (sqlite3.Error,OSError):
            self.saved.setText('Не удалось сохранить. Текст остаётся в окне; попробуй ещё раз.')
            return False

    def update_state(self):
        self.record=learning.progress(self.lesson_id)
        self.state_label.setText(learning.STATES[self.record['state']]+' · '+self.item['minutes']+' минут · правильность SQL не подтверждена')
        self.complete_button.setText('Вернуть в работу' if self.record['state']=='completed_user' else 'Отметить завершённым')

    def update_hints(self):
        count=learning.progress(self.lesson_id)['hints_revealed']
        self.hints.setPlainText('\n\n'.join(f'{i+1}. {hint}' for i,hint in enumerate(self.item['hints'][:count])) or 'Подсказки пока не открыты.')
        self.hint_button.setText(f'Следующая подсказка · {count}/{len(self.item["hints"])}')
        self.hint_button.setDisabled(count==len(self.item['hints']))

    def hint(self):
        if not self.flush():return
        learning.reveal_hint(self.lesson_id); self.update_hints()

    def solution(self):
        if not self.flush():return
        self.solution_visible=not self.solution_visible
        if self.solution_visible:
            learning.reveal_solution(self.lesson_id)
            self.solution_view.setPlainText(self.item['solution']+'\n\nРАЗБОР\n'+self.item['solution_notes'])
        self.solution_view.setVisible(self.solution_visible)
        self.solution_button.setText('Скрыть эталон' if self.solution_visible else 'Показать эталон (открывался раньше)')

    def toggle_complete(self):
        if not self.flush():return
        if learning.progress(self.lesson_id)['state']=='completed_user':
            learning.save_progress(self.lesson_id,state='in_progress'); learning.set_profile(active_lesson=self.lesson_id)
        else:learning.complete(self.lesson_id)
        self.update_state(); self.owner.learning_page.refresh()

    def next_lesson(self):
        if not self.flush():return
        current=learning.current_lesson()
        if current and current['id']!=self.lesson_id:
            self.owner.open_learning(current['id']); self.close()
        elif current:
            self.saved.setText('Сначала заверши текущее занятие или выбери другое в разделе «Обучение».')
        else:self.saved.setText('Стартовый набор завершён тобой. Можно повторить любой материал.')

    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'Сохранить учебные данные','orbita-db2-fixture.sql','SQL (*.sql)')
        if path:
            try:learning.export_fixture(path)
            except OSError as exc:QMessageBox.warning(self,'Не удалось сохранить файл',str(exc))

    def question(self):
        if not self.flush():return
        dialog=QDialog(self); dialog.setWindowTitle('Вопрос для Codex'); dialog.resize(790,630)
        layout=QVBoxLayout(dialog); layout.addWidget(label('Текст только готовится для копирования. Автоматической отправки нет.',12))
        question=QLineEdit(); question.setPlaceholderText('Что именно хочешь уточнить?'); layout.addWidget(question)
        preview=plain(learning.codex_question(self.lesson_id,'')); preview.setObjectName('codexQuestion'); layout.addWidget(preview,1)
        status=label('',11); layout.addWidget(status)
        def generate(copy=False):
            if not self.flush():return
            value=learning.codex_question(self.lesson_id,question.text()); preview.setPlainText(value)
            if copy:QApplication_clipboard(value); status.setText('Скопировано. Ничего не отправлено.')
        controls=QHBoxLayout(); controls.addWidget(btn('Обновить текст',lambda:generate(False)))
        controls.addWidget(btn('Скопировать',lambda:generate(True),True)); controls.addWidget(btn('Закрыть',dialog.close))
        layout.addLayout(controls); dialog.show()

    def closeEvent(self,event):
        if not self.flush():event.ignore(); return
        self.owner.learning_page.refresh(); event.accept()


def QApplication_clipboard(text):
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setText(text)
