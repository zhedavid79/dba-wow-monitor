import unittest

import dba_report_v6 as m


class HighRecallTests(unittest.TestCase):
    def test_price_binding_fixture(self):
        self.assertTrue(m.fixture_regression()['ok'])

    def test_generic_oem_pc_advances_without_gpu_in_title(self):
        row = {'title': 'HP Omen 25L gaming computer', 'price': 3200, 'queries': ['hp omen']}
        self.assertTrue(m.should_advance_t0(row))

    def test_component_title_is_not_complete_pc(self):
        ok, _ = m.complete_system_evidence('ASUS GeForce RTX 3070 grafikkort', '', ['rtx 3070'])
        self.assertFalse(ok)

    def test_description_can_resolve_specs(self):
        gpu, gs, cpu, cs, source = m.resolve_specs('Gaming PC', 'RTX 3070 og Ryzen 5 5600X', {})
        self.assertEqual(gpu, 'RTX 3070')
        self.assertEqual(cpu, 'Ryzen 5 5600X')
        self.assertGreaterEqual(gs, 65)
        self.assertGreaterEqual(cs, 60)
        self.assertIn('description', source)

    def test_price_first_classification(self):
        self.assertEqual(m.perf(73, 65), 'SWEET SPOT')
        self.assertEqual(m.perf(54, 65), 'ACCEPTABLE')


if __name__ == '__main__':
    unittest.main()
