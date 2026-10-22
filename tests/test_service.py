import os
import unittest

os.environ["NOC_MODE"] = "mock"

from ttn_noc.service import NocService


class NocServiceTests(unittest.TestCase):
    def test_mock_snapshot_has_gateway_and_sensor_metrics(self):
        data = NocService().status()
        self.assertEqual(data["mode"], "mock")
        self.assertEqual(data["summary"]["gateways_total"], 2)
        self.assertEqual(data["summary"]["sensors_total"], 2)
        self.assertGreaterEqual(data["summary"]["gateways_offline"], 1)
        self.assertEqual(data["summary"]["sensors_online"], 1)
        self.assertEqual(data["summary"]["sensors_offline"], 1)
        self.assertEqual(data["gateways"][0]["latitude"], -34.406)
        self.assertEqual(data["gateways"][0]["longitude"], -70.858)
        self.assertEqual(data["gateways"][0]["ttn_console_url"], "https://eu1.cloud.thethings.network/console/gateways/gw-rengo-01")


if __name__ == "__main__":
    unittest.main()
