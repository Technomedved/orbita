import unittest
from orbita_glass import condition


class WeatherConditions(unittest.TestCase):
    def test_wmo_groups(self):
        groups={'sun':[0], 'partly':[1,2], 'cloud':[3], 'fog':[45,48],
                'rain':[51,53,55,56,57,61,63,65,66,67,80,81,82],
                'snow':[71,73,75,77,85,86], 'storm':[95,96,99]}
        for kind,codes in groups.items():
            for code in codes:
                with self.subTest(code=code):self.assertEqual(condition(code)[0],kind)

    def test_night_and_unknown(self):
        self.assertEqual(condition(0,False)[0],'moon')
        self.assertEqual(condition(2,False)[0],'nightcloud')
        self.assertEqual(condition(123)[0],'unknown')


if __name__=='__main__':unittest.main()
