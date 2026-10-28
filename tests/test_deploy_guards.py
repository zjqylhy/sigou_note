import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('deploy_site', Path(__file__).parents[1] / 'scripts/deploy_site.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class DeploymentGuards(unittest.TestCase):
    def setUp(self):
        self.before = {'edge': {'image': 'existing-caddy', 'volumes': [
            {'target': '/data', 'source': 'persistent-certificate-volume', 'type': 'volume'}]},
            'admin': {'image': 'existing-admin', 'environment': {'ORIGIN': 'https://console.example'}}}
        self.after = copy.deepcopy(self.before)
        self.after['edge']['volumes'].extend([
            {'target': '/srv/sigou-notes', 'source': '/opt/sigou-notes/site', 'type': 'bind', 'read_only': True},
            {'target': '/etc/caddy/sigou-notes.caddy', 'source': '/opt/sigou-notes/deploy/site.caddy', 'type': 'bind', 'read_only': True}])

    def test_only_expected_readonly_mounts_allowed(self):
        module.check_services(self.before, self.after)

    def test_business_service_change_rejected(self):
        self.after['admin']['environment']['ORIGIN'] = 'https://wrong.example'
        with self.assertRaises(RuntimeError):
            module.check_services(self.before, self.after)

    def test_certificate_volume_replacement_rejected(self):
        self.after['edge']['volumes'][0]['source'] = 'empty-new-volume'
        with self.assertRaises(RuntimeError):
            module.check_services(self.before, self.after)

    def test_writable_site_mount_rejected(self):
        self.after['edge']['volumes'][1]['read_only'] = False
        with self.assertRaises(RuntimeError):
            module.check_services(self.before, self.after)

    def test_extra_mount_rejected(self):
        self.after['edge']['volumes'].append({'target': '/secret', 'source': '/private', 'type': 'bind'})
        with self.assertRaises(RuntimeError):
            module.check_services(self.before, self.after)

    def test_added_service_rejected(self):
        self.after['unexpected'] = {'image': 'other'}
        with self.assertRaises(RuntimeError):
            module.check_services(self.before, self.after)

if __name__ == '__main__':
    unittest.main()
