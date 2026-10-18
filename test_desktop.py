import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import desktop_store as store


class InboxTests(unittest.TestCase):
    def test_deduplication_and_read_state(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'HOME', Path(folder)):
            first = store.publish('Title', 'Body', 'Проекты', 'same-result')
            self.assertIsNotNone(first)
            self.assertIsNone(store.publish('Title', 'Body', 'Проекты', 'same-result'))
            self.assertEqual(len(store.events()), 1)
            self.assertEqual(store.events()[0]['seen'], 0)
            store.mark_seen(first)
            self.assertEqual(store.events()[0]['seen'], 1)

    def test_external_publisher_preserves_unicode(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'HOME', Path(folder)):
            source = Path(folder) / 'event.json'
            source.write_text(json.dumps({'title': 'Погода', 'body': 'Урай: +4 °C', 'category': 'Погода'}), encoding='utf-8')
            env = dict(os.environ, AUTOMATION_HOME=folder)
            result = subprocess.run([sys.executable, str(Path(__file__).parent / 'publish.py'), '--file', str(source)],
                                    env=env, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(store.events()[0]['body'], 'Урай: +4 °C')

    def test_settings_survive_reopening(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'HOME', Path(folder)):
            self.assertFalse(store.get_setting('weather_enabled', False))
            store.set_setting('weather_enabled', True)
            self.assertTrue(store.get_setting('weather_enabled'))


if __name__ == '__main__':
    unittest.main()
