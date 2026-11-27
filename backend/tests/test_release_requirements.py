import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('verify_requirements', Path(__file__).resolve().parents[2] / 'deploy/verify_requirements.py')
requirements = importlib.util.module_from_spec(spec)
spec.loader.exec_module(requirements)


class ReleaseRequirementsTests(unittest.TestCase):
    def test_prepared_versions_pass_with_comments_and_blank_lines(self):
        with patch.object(requirements, 'version', side_effect=lambda name: {'Pillow': '13.0.0', 'fastapi': '0.104.1'}[name]):
            self.assertEqual(requirements.mismatches('# release\nPillow==13.0.0\n\nfastapi==0.104.1'), [])

    def test_wrong_and_missing_versions_block_release(self):
        with patch.object(requirements, 'version', return_value='12.0.0'):
            self.assertEqual(len(requirements.mismatches('Pillow==13.0.0')), 1)
        with patch.object(requirements, 'version', side_effect=requirements.PackageNotFoundError):
            self.assertIn('missing', requirements.mismatches('Pillow==13.0.0')[0])

    def test_unpinned_dependencies_and_includes_require_explicit_support(self):
        self.assertEqual(len(requirements.mismatches('Pillow>=13\n-r other.txt\nhttps://example.org/package.whl')), 3)
