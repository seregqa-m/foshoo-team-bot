"""No real systemctl, npm, signals, credentials or production services are used."""
import importlib.util
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/botctl.py'
spec = importlib.util.spec_from_file_location('botctl', SCRIPT)
botctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(botctl)


class BotControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        root_patch = patch.object(botctl, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.frontend = self.root / 'frontend'
        self.live = self.frontend / 'build'
        self.live.mkdir(parents=True)
        (self.live / 'index.html').write_text('old version')

    def process(self, pid, *, cwd=None, script='backend/main.py', cgroup='0::/user.slice/session.scope'):
        directory = self.root / 'proc' / str(pid)
        directory.mkdir(parents=True)
        (directory / 'cmdline').write_bytes(f'/usr/bin/python3\0{script}\0'.encode())
        (directory / 'cwd').symlink_to(cwd or self.root)
        (directory / 'cgroup').write_text(cgroup)
        (directory / 'stat').write_text(f'{pid} (python3) S ' + '0 ' * 18 + '100')
        return directory

    def test_failed_build_keeps_live_frontend(self):
        with patch.object(botctl, 'run', side_effect=[None, subprocess.CalledProcessError(1, ['npm'])]):
            with self.assertRaises(subprocess.CalledProcessError):
                botctl.build_frontend()
        self.assertEqual((self.live / 'index.html').read_text(), 'old version')
        self.assertEqual(list(self.frontend.glob('.bot-build-*')), [])

    def test_successful_build_is_staged_and_uses_frontend_directory(self):
        def run(*args, **kwargs):
            self.assertEqual(kwargs['cwd'], self.frontend)
            self.assertEqual((self.live / 'index.html').read_text(), 'old version')
            if args == ('npm', 'run', 'build'):
                stage = Path(kwargs['env']['BUILD_PATH'])
                self.assertNotEqual(stage, self.live)
                stage.mkdir()
                (stage / 'index.html').write_text('new version')
        with patch.object(botctl, 'run', side_effect=run) as mocked:
            botctl.build_frontend()
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual((self.live / 'index.html').read_text(), 'new version')

    def test_failed_publish_restores_previous_frontend(self):
        original = Path.rename

        def rename(source, target):
            if source.name == 'build' and source != self.live:
                raise OSError('rename failed')
            return original(source, target)

        def run(*args, **kwargs):
            if args == ('npm', 'run', 'build'):
                stage = Path(kwargs['env']['BUILD_PATH'])
                stage.mkdir()
                (stage / 'index.html').write_text('new version')
        with patch.object(botctl, 'run', side_effect=run), patch.object(Path, 'rename', rename):
            with self.assertRaises(OSError):
                botctl.build_frontend()
        self.assertEqual((self.live / 'index.html').read_text(), 'old version')

    def test_legacy_lookup_ignores_other_projects_and_managed_service(self):
        expected = self.process(10)
        self.process(11, script='other/main.py')
        self.process(12, cgroup=f'0::/system.slice/{botctl.SERVICE}')
        self.assertEqual(botctl.legacy_processes(self.root / 'proc'), [(expected, '100')])

    def test_different_working_directory_requires_database_check(self):
        backend = self.root / 'backend'
        backend.mkdir()
        self.process(10, cwd=backend, script='main.py')
        with self.assertRaisesRegex(RuntimeError, 'путь к его БД'):
            botctl.legacy_processes(self.root / 'proc')

    def test_pid_reuse_is_not_signalled(self):
        with patch.object(botctl, 'process_identity', return_value='new'), patch.object(botctl.os, 'pidfd_open', create=True) as pidfd:
            botctl.stop_legacy([(Path('/proc/42'), 'old')])
        pidfd.assert_not_called()

    def test_legacy_stop_sends_term_to_checked_pid_and_waits(self):
        with patch.object(botctl, 'process_identity', side_effect=['100', '100', None]), \
                patch.object(botctl.os, 'pidfd_open', return_value=17, create=True) as opened, \
                patch.object(botctl.signal, 'pidfd_send_signal', create=True) as sent, \
                patch.object(botctl.os, 'close') as closed:
            botctl.stop_legacy([(Path('/proc/42'), '100')])
        opened.assert_called_once_with(42)
        sent.assert_called_once_with(17, botctl.signal.SIGTERM)
        closed.assert_called_once_with(17)

    def test_stuck_legacy_process_causes_failure_instead_of_second_start(self):
        with patch.object(botctl, 'process_identity', return_value='100'), \
                patch.object(botctl.os, 'pidfd_open', return_value=17, create=True), \
                patch.object(botctl.signal, 'pidfd_send_signal', create=True), patch.object(botctl.os, 'close'), \
                patch.object(botctl.time, 'monotonic', side_effect=[0, 41]):
            with self.assertRaisesRegex(RuntimeError, 'Новая служба не запущена'):
                botctl.stop_legacy([(Path('/proc/42'), '100')])

    def test_unit_keeps_root_and_virtualenv_and_waits_for_health(self):
        python = self.root / 'venv/bin/python3'
        with patch.object(botctl, 'python_path', return_value=python):
            unit = botctl.unit_text()
        self.assertIn(f'WorkingDirectory={self.root}\n', unit)
        self.assertIn(f'ExecStart="{python}" "{self.root}/backend/main.py"', unit)
        self.assertIn('scripts/botctl.py" health', unit)
        self.assertIn('Restart=on-failure', unit)
        self.assertIn('Environment=API_RELOAD=false', unit)
        self.assertNotIn('EnvironmentFile=', unit)

    def test_unit_paths_escape_special_characters(self):
        self.assertEqual(botctl.unit_quote('/a%/b$ c', command=True), '"/a%%/b$$ c"')
        with self.assertRaises(RuntimeError):
            botctl.unit_quote('/path\nExecStart=other')

    @unittest.skipUnless(sys.platform == 'linux' and shutil.which('systemd-analyze'),
                         'Requires the real systemd parser on Linux')
    def test_real_systemd_parser_accepts_unit_and_rejects_old_quoted_directory(self):
        # No daemon is started: verify only parses the unit and its dependencies.
        # Spaces and % must survive without shell-style quoting in WorkingDirectory.
        root = self.root / 'project with spaces 100%'
        root.mkdir()
        with patch.object(botctl, 'ROOT', root), patch.object(botctl, 'python_path', return_value=Path(sys.executable)):
            content = botctl.unit_text()
        unit = self.root / botctl.SERVICE
        unit.write_text(content)
        valid = subprocess.run(['systemd-analyze', 'verify', str(unit)], capture_output=True, text=True, timeout=30)
        self.assertEqual(valid.returncode, 0, valid.stderr)
        working_directory = f'WorkingDirectory={str(root).replace("%", "%%")}'
        unit.write_text(content.replace(working_directory, f'WorkingDirectory={botctl.unit_quote(root)}'))
        invalid = subprocess.run(['systemd-analyze', 'verify', str(unit)], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn('WorkingDirectory=', invalid.stderr)

    def test_health_uses_configured_port_and_bypasses_network_proxy(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"status":"healthy"}'
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(botctl, 'app_config', return_value=SimpleNamespace(API_HOST='::', API_PORT=9000)), \
                patch.object(botctl, 'build_opener', return_value=opener), patch.object(botctl, 'ProxyHandler') as proxy:
            botctl.wait_health()
        proxy.assert_called_once_with({})
        opener.open.assert_called_once_with('http://[::1]:9000/health', timeout=1)

    def test_failed_build_never_restarts_service(self):
        exists = Path.is_dir
        with patch.object(botctl.sys, 'platform', 'linux'), \
                patch.object(Path, 'is_dir', lambda p: True if str(p) == '/run/systemd/system' else exists(p)), \
                patch.object(botctl.os, 'getuid', return_value=1000), \
                patch.object(botctl.sys, 'argv', ['bot', 'restart', '--build']), \
                patch.object(botctl, 'check_service'), patch.object(botctl, 'run'), \
                patch.object(botctl, 'build_frontend', side_effect=RuntimeError('build failed')), \
                patch.object(botctl, 'restart') as restart:
            with self.assertRaisesRegex(RuntimeError, 'build failed'):
                botctl.main()
        restart.assert_not_called()

    def test_foreign_unit_is_not_overwritten(self):
        unit = self.root / 'foreign.service'
        unit.write_text('# someone else\n[Service]\n')
        with patch.object(botctl, 'UNIT', unit):
            with self.assertRaisesRegex(RuntimeError, 'другой установке'):
                botctl.setup()

    def test_install_verification_failure_does_not_stop_running_backend(self):
        unit = self.root / 'new.service'
        def run(*args, **kwargs):
            if args[0] == 'systemd-analyze':
                raise subprocess.CalledProcessError(1, ['systemd-analyze'])
        with patch.object(botctl, 'UNIT', unit), patch.object(botctl, 'legacy_processes', return_value=[]), \
                patch.object(botctl, 'unit_text', return_value='unit'), patch.object(botctl, 'python_path', return_value='/fake/python'), \
                patch.object(botctl, 'run', side_effect=run), patch.object(botctl, 'stop_legacy') as stop:
            with self.assertRaises(subprocess.CalledProcessError):
                botctl.setup()
        stop.assert_not_called()
        self.assertFalse(unit.exists())
