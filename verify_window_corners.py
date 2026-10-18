"""Native compositor verification on controlled backgrounds and an isolated DB.

Unlike QWidget.grab(), the screen capture includes effects applied by Windows.
Can run both from Python and from the packaged exe before its regular startup.
"""
import argparse
import json
from pathlib import Path
import tempfile


def verify(prefix,strict=False):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter,QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QWidget
    import desktop_store as store
    from orbita_glass import Window

    class Backdrop(QWidget):
        def __init__(self):
            super().__init__();self.dark=False
            self.setWindowFlags(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint)
            self.setWindowTitle('Orbita corner verification backdrop')

        def paintEvent(self,event):
            p=QPainter(self)
            colors=['#eeeef5','#dd557e'] if not self.dark else ['#0c1424','#214a5b']
            for y in range(0,self.height(),16):
                for x in range(0,self.width(),16):p.fillRect(x,y,16,16,QColor(colors[((x//16)+(y//16))%2]))

    scratch=tempfile.TemporaryDirectory(prefix='orbita-corners-');previous_home=store.HOME
    store.HOME=Path(scratch.name)
    # New profiles are unpinned. Keep this test's backdrop and panel in a
    # controlled topmost layer so an active unrelated app cannot occlude them.
    store.set_setting('topmost',True)
    app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
    screen=app.primaryScreen();area=screen.availableGeometry()
    backdrop=Backdrop();backdrop.setGeometry(area);backdrop.show();backdrop.raise_();QTest.qWait(250)
    window=Window();window.resize(640,min(660,area.height()-120));window.move(area.left()+45,area.top()+45)
    window.switch_page(4)
    prefix=Path(prefix).resolve();prefix.parent.mkdir(parents=True,exist_ok=True)
    report={'tag':prefix.name,'qt_scale':window.devicePixelRatioF(),
            'controlled_topmost_fixture':True,'pin_roundtrip':True,'scenarios':[]}

    def capture():
        pos=window.pos()
        return screen.grabWindow(0,pos.x(),pos.y(),window.width(),window.height()).toImage()

    def check(name):
        window.hide();backdrop.raise_();backdrop.update();QTest.qWait(200)
        expected=capture()
        window.show();window.raise_();QTest.qWait(450)
        actual=capture();actual.save(str(prefix)+f'-{name}.png')
        center=actual.pixelColor(actual.width()//2,actual.height()//2)
        behind=expected.pixelColor(expected.width()//2,expected.height()//2)
        assert sum(abs(a-b) for a,b in zip(center.getRgb()[:3],behind.getRgb()[:3]))>20,'Panel was occluded; compositor sample is invalid'
        rgba=window.grab().toImage();rgba.save(str(prefix)+f'-alpha-{name}.png')
        sx=actual.width()/window.width();sy=actual.height()/window.height();points=[]
        for side_x,side_y in ((0,0),(1,0),(0,1),(1,1)):
            for dx,dy in ((2,2),(5,5),(2,12),(12,2)):
                x=dx if not side_x else window.width()-1-dx;y=dy if not side_y else window.height()-1-dy
                px=min(actual.width()-1,int((x+.5)*sx));py=min(actual.height()-1,int((y+.5)*sy))
                a=actual.pixelColor(px,py);b=expected.pixelColor(px,py)
                delta=max(abs(a.red()-b.red()),abs(a.green()-b.green()),abs(a.blue()-b.blue()))
                points.append({'logical':[x,y],'rgb_delta':delta,'alpha':rgba.pixelColor(px,py).alpha()})
        report['scenarios'].append({'name':name,'size':[window.width(),window.height()],
            'max_outside_rgb_delta':max(p['rgb_delta'] for p in points),
            'max_outside_alpha':max(p['alpha'] for p in points),'samples':points})

    try:
        check('light');backdrop.dark=True;check('dark')
        window.resize(590,min(590,area.height()-130));check('resized')
        window.toggle_pin();window.toggle_pin();check('repinned')
        window.hide();QTest.qWait(100);window.reveal();check('restored')
        Path(str(prefix)+'-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if strict:
            assert all(row['max_outside_rgb_delta']==0 and row['max_outside_alpha']==0 for row in report['scenarios']), 'Compositor changed transparent corner pixels'
        return report
    finally:
        window.engine.stop();window.timer.stop();window.tray.hide();window.quitting=True
        window.revision_reader.close();window.close();backdrop.close();app.processEvents()
        store.HOME=previous_home;scratch.cleanup()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--tag',default='after');parser.add_argument('--assert-clear',action='store_true')
    args=parser.parse_args()
    report=verify(Path(__file__).resolve().parent/'data'/('corners-'+args.tag),args.assert_clear)
    print(json.dumps({'tag':report['tag'],'qt_scale':report['qt_scale'],
                      'scenarios':[{k:v for k,v in row.items() if k!='samples'} for row in report['scenarios']]}))
