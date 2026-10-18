import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import weather


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.logging_patch = patch.object(weather.logging, 'basicConfig')
        self.logging_patch.start()
        self.addCleanup(self.logging_patch.stop)

    def test_daily_duplicate_does_not_fetch_or_send(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            day = str(weather.datetime.now(weather.LOCAL).date())
            (data / f"sent-{day}.json").write_text('{}')
            with patch.object(weather, 'DATA', data), patch('sys.argv', ['weather.py', '--send']), \
                    patch.object(weather, 'forecast') as fetch, patch.object(weather, 'send') as send:
                weather.main()
            fetch.assert_not_called()
            send.assert_not_called()
            self.assertFalse((data / 'send.lock').exists())

    def test_missing_weather_sends_failure_instead_of_old_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / 'preview.txt').write_text('old forecast')
            with patch.object(weather, 'DATA', data), patch('sys.argv', ['weather.py', '--send', '--test']), \
                    patch.object(weather, 'forecast', side_effect=OSError), \
                    patch.object(weather, 'send') as send:
                weather.main()
            subject, body = send.call_args.args[:2]
            self.assertIn('недоступен', subject)
            self.assertNotIn('old forecast', body)
            self.assertFalse((data / 'send.lock').exists())

    def test_smtp_error_does_not_record_success(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / 'mail.local.json').write_text(json.dumps({'sender': 'a@yandex.ru', 'recipient': 'a@yandex.ru'}))
            with patch.object(weather, 'ROOT', data), patch.object(weather, 'DATA', data), \
                    patch.dict(weather.os.environ, {'URAY_SMTP_PASSWORD': 'test-only'}), \
                    patch.object(weather.smtplib, 'SMTP_SSL', side_effect=OSError):
                with self.assertRaises(OSError):
                    weather.send('test', 'test', '2026-10-15')
            self.assertFalse((data / 'sent-2026-10-15.json').exists())


if __name__ == '__main__':
    unittest.main()
