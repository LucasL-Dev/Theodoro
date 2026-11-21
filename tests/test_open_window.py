import unittest
from threading import Event
from unittest.mock import Mock

from theodoro.open_window import DEMO_PATH, OpenChrome, approved_address


class OpenWindowTests(unittest.TestCase):
    def test_only_exact_premier_origin_or_shipped_fixture(self):
        self.assertTrue(approved_address('https://inside.premierdelivery.com.br/financeiro', False))
        self.assertTrue(approved_address(DEMO_PATH.resolve().as_uri(), True))
        for url in ('https://inside.premierdelivery.com.br.evil.test',
                    'http://inside.premierdelivery.com.br',
                    'https://another@inside.premierdelivery.com.br',
                    'https://inside.premierdelivery.com.br:1234',
                    'file:///C:/other/window_demo.html'):
            self.assertFalse(approved_address(url, False))
        self.assertFalse(approved_address('file:///C:/other/window_demo.html', True))

    def test_checks_all_existing_values_before_any_write(self):
        adapter = OpenChrome(Event())
        net = Mock()
        net.iface_value.CurrentValue = ''
        payout = Mock()
        payout.iface_value.CurrentValue = '97,00'
        adapter.target = Mock(return_value=(None, ('url', (1,))))
        adapter.fields = Mock(return_value={'Líquido': net, 'Repasse': payout})
        with self.assertRaisesRegex(ValueError, 'já tem outro valor'):
            adapter.fill((1, 2), False, {'net': 'Líquido', 'payout': 'Repasse'},
                         {'net': 13000, 'payout': 8000}, 'br')
        net.iface_value.SetValue.assert_not_called()

    def test_cancellation_prevents_the_next_write(self):
        stop = Event()
        adapter = OpenChrome(stop)
        net, payout = Mock(), Mock()
        net.iface_value.CurrentValue = ''
        payout.iface_value.CurrentValue = ''
        net.iface_value.SetValue.side_effect = lambda *_: stop.set()
        adapter.target = Mock(return_value=(None, ('url', (1,))))
        adapter.fields = Mock(return_value={'Líquido': net, 'Repasse': payout})
        with self.assertRaisesRegex(ValueError, 'interrompido'):
            adapter.fill((1, 2), False, {'net': 'Líquido', 'payout': 'Repasse'},
                         {'net': 13000, 'payout': 8000}, 'br')
        net.iface_value.SetValue.assert_called_once_with('130,00')
        payout.iface_value.SetValue.assert_not_called()
