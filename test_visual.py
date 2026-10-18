"""Visual regressions checked on rendered widgets, using a temporary database."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QCheckBox,QDialog
import desktop_store as store
import project_service as projects
from orbita_glass import Window,Toast

app=QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)


def outside_samples(widget):
    image=widget.grab().toImage();scale=image.devicePixelRatio()
    return [image.pixelColor(int(x*scale),int(y*scale)).alpha()
            for x in (2,widget.width()-3) for y in (2,widget.height()-3)]


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.patch=patch.object(store,'HOME',Path(self.temp.name));self.patch.start()
        self.window=Window();self.window.show();QTest.qWait(60)

    def tearDown(self):
        self.window.engine.stop();self.window.quitting=True;self.window.timer.stop();self.window.tray.hide()
        for child in self.window.findChildren(QDialog):child.close()
        for toast in self.window.toasts:toast.close()
        self.window.revision_reader.close();self.window.close();self.window.deleteLater();QTest.qWait(40)
        self.patch.stop();self.temp.cleanup()

    def test_corner_alpha_survives_resize_tray_restore_and_pin_change(self):
        for width,height in ((640,650),(550,510)):
            self.window.resize(width,height);QTest.qWait(40)
            self.assertEqual(outside_samples(self.window),[0]*4)
        self.window.hide();self.window.reveal();self.window.toggle_pin();QTest.qWait(50)
        self.assertEqual(outside_samples(self.window),[0]*4)
        image=self.window.grab().toImage();scale=image.devicePixelRatio()
        arc=[image.pixelColor(x,y).alpha() for x in range(int(35*scale)) for y in range(int(35*scale))]
        self.assertTrue(any(0<alpha<240 for alpha in arc),'Rounded edge must retain antialiasing')

    def test_new_checkbox_style_preserves_keyboard_checklist_interaction(self):
        key=projects.create('Клавиатурная проверка','print');step=projects.get(key)['steps'][0]
        self.window.open_project(key);dialog=self.window.project_dialogs[key]
        for expected in (1,0):
            check=dialog.findChild(QCheckBox,'projectStep_'+step['id']);check.setFocus()
            QTest.keyClick(check,Qt.Key_Space);QTest.qWait(50)
            self.assertEqual(projects.get(key)['steps'][0]['done'],expected)

    def test_notification_has_clear_corners_and_readable_background(self):
        toast=Toast({'title':'Контрастное уведомление','body':'Текст должен оставаться читаемым на светлом фоне.','category':'Проекты'},self.window)
        try:
            QTest.qWait(500);self.assertEqual(outside_samples(toast),[0]*4)
            image=toast.grab().toImage();scale=image.devicePixelRatio()
            self.assertGreaterEqual(image.pixelColor(int(16*scale),int(toast.height()/2*scale)).alpha(),245)
        finally:toast.close()


if __name__=='__main__':unittest.main()
