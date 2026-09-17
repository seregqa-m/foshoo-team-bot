"""Server lifecycle commands. Does not import or start the bot in the CLI process."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent.parent
SERVICE = 'foshoo-bot.service'
UNIT = Path('/etc/systemd/system') / SERVICE


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def python_path():
    for relative in ('venv/bin/python3', 'backend/venv/bin/python3'):
        path = ROOT / relative
        if path.is_file() and os.access(path, os.X_OK):
            return path  # Do not resolve the symlink: it identifies the virtualenv.
    raise RuntimeError('Не найден Python в venv/bin/python3 или backend/venv/bin/python3.')


def unit_quote(value, command=False):
    value = str(value)
    if '\n' in value or '\r' in value:
        raise RuntimeError('Переносы строк в пути проекта не поддерживаются.')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    if command:
        value = value.replace('$', '$$')
    return f'"{value}"'


def unit_text():
    python = unit_quote(python_path(), command=True)
    # WorkingDirectory is a scalar path, not an ExecStart-style argument list:
    # systemd preserves surrounding quotes here. Only escape specifiers.
    working_directory = str(ROOT).replace('%', '%%')
    return f'''# Managed by FoShoo bot setup: {ROOT}
[Unit]
Description=FoShoo Telegram bot and API
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
User={os.getuid()}
Group={os.getgid()}
WorkingDirectory={working_directory}
Environment=PYTHONUNBUFFERED=1
Environment=API_RELOAD=false
ExecStart={python} {unit_quote(ROOT / 'backend/main.py', command=True)}
ExecStartPost={python} {unit_quote(ROOT / 'scripts/botctl.py', command=True)} health
Restart=on-failure
RestartSec=5
TimeoutStartSec=45
TimeoutStopSec=40
KillMode=control-group
StandardOutput=journal
StandardError=journal
SyslogIdentifier=foshoo-bot

[Install]
WantedBy=multi-user.target
'''


def build_frontend():
    print('Устанавливаю зависимости и собираю фронт. Текущая версия пока работает.', flush=True)
    frontend = ROOT / 'frontend'
    live = frontend / 'build'
    if live.is_symlink():
        raise RuntimeError('frontend/build — ссылка. Её схему публикации нужно настроить отдельно.')
    run('npm', 'ci', cwd=frontend)
    with tempfile.TemporaryDirectory(prefix='.bot-build-', dir=frontend) as directory:
        stage = Path(directory) / 'build'
        run('npm', 'run', 'build', cwd=frontend, env={**os.environ, 'BUILD_PATH': str(stage)})
        if not (stage / 'index.html').is_file():
            raise RuntimeError('Сборка не создала index.html; рабочий фронт не заменён.')
        previous = Path(directory) / 'previous'
        if live.exists():
            live.rename(previous)
        try:
            stage.rename(live)
        except OSError:
            if previous.exists():
                previous.rename(live)
            raise
    print('Фронт собран и опубликован в frontend/build.', flush=True)


def process_identity(directory):
    """PID start time prevents waiting on an unrelated recycled PID."""
    try:
        fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (OSError, IndexError):
        return None


def legacy_processes(proc=Path('/proc')):
    result = []
    for directory in proc.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue
            # setup may be repeated, including after an interrupted migration.
            if any(SERVICE in line.split(':', 2)[-1].strip().split('/')
                   for line in (directory / 'cgroup').read_text().splitlines()):
                continue
            args = (directory / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
            if not args or not re.fullmatch(r'python(?:[0-9]+(?:\.[0-9]+)?)?', Path(args[0]).name):
                continue
            arguments = args[1:]
            if arguments[:1] == ['-u']:
                arguments = arguments[1:]
            if len(arguments) != 1:
                continue
            cwd = (directory / 'cwd').resolve(strict=True)
            script = (cwd / arguments[0]).resolve()
            if script != ROOT / 'backend/main.py':
                continue
            if cwd != ROOT:
                raise RuntimeError('Старый backend запущен не из корня проекта. Сначала нужно сверить путь к его БД.')
            identity = process_identity(directory)
            if identity:
                result.append((directory, identity))
        except (OSError, UnicodeError):
            continue
    return result


def stop_legacy(processes):
    for directory, identity in processes:
        if process_identity(directory) != identity:
            continue
        pid = int(directory.name)
        print(f'Останавливаю прежний backend (PID {pid})…', flush=True)
        try:
            # pidfd binds the signal to this process, even if the PID is reused.
            descriptor = os.pidfd_open(pid)
            try:
                if process_identity(directory) == identity:
                    signal.pidfd_send_signal(descriptor, signal.SIGTERM)
            finally:
                os.close(descriptor)
        except ProcessLookupError:
            continue
    deadline = time.monotonic() + 40
    while any(process_identity(path) == identity for path, identity in processes):
        if time.monotonic() >= deadline:
            raise RuntimeError('Прежний backend не завершился за 40 секунд. Новая служба не запущена.')
        time.sleep(0.25)


def check_service():
    if not UNIT.is_file():
        raise RuntimeError('Служба ещё не установлена. Выполните ./bot setup --build.')
    if UNIT.read_text().splitlines()[:1] != [f'# Managed by FoShoo bot setup: {ROOT}']:
        raise RuntimeError('Служба foshoo-bot принадлежит другой установке. Её настройки не изменены.')


def restart():
    print('Перезапускаю backend и жду ответа /health…', flush=True)
    run('sudo', 'systemctl', 'reset-failed', SERVICE)
    run('sudo', 'systemctl', 'restart', SERVICE)
    run('systemctl', 'is-active', '--quiet', SERVICE)
    print('Готово: backend отвечает. Логи: ./bot logs', flush=True)


def setup(build=False):
    print('Проверяю настройки службы…', flush=True)
    if UNIT.exists():
        check_service()
    processes = legacy_processes()
    if processes and (not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal')):
        raise RuntimeError('Для автоматического перехода с nohup нужен Python 3.9+ и Linux 5.3+.')
    content = unit_text()
    run(python_path(), ROOT / 'scripts/botctl.py', 'check-config', cwd=ROOT)
    if build:
        build_frontend()
    with tempfile.TemporaryDirectory(prefix='foshoo-service-') as directory:
        source = Path(directory) / SERVICE
        source.write_text(content)
        # Verify the exact unit before touching the old process or system config.
        print('Проверяю файл службы через systemd-analyze…', flush=True)
        run('systemd-analyze', 'verify', source)
        print('Устанавливаю службу systemd…', flush=True)
        run('sudo', 'install', '-m', '644', source, UNIT)
    run('sudo', 'systemctl', 'daemon-reload')
    stop_legacy(processes)
    run('sudo', 'systemctl', 'enable', SERVICE)
    restart()


def app_config():
    sys.path.insert(0, str(ROOT / 'backend'))
    import config
    return config


def wait_health():
    config = app_config()
    host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(config.API_HOST, config.API_HOST)
    host = f'[{host}]' if ':' in host else host
    url = f'http://{host}:{config.API_PORT}/health'
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=1) as response:
                if response.status == 200 and json.load(response).get('status') == 'healthy':
                    return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError('Backend не ответил на /health за 35 секунд.')


def main():
    parser = argparse.ArgumentParser(description='FoShoo: запуск и перезапуск сервера одной командой')
    parser.add_argument('command', choices=['setup', 'restart', 'status', 'logs', 'health', 'check-config'])
    parser.add_argument('--build', action='store_true', help='сначала установить зависимости и пересобрать фронт')
    args = parser.parse_args()
    if args.build and args.command not in ('setup', 'restart'):
        parser.error('--build доступен только для setup и restart')
    if args.command == 'health':
        wait_health()
        return
    if args.command == 'check-config':
        app_config()
        return
    if sys.platform != 'linux' or not Path('/run/systemd/system').is_dir():
        raise RuntimeError('Эта команда предназначена для Linux-сервера с systemd.')
    if os.getuid() == 0:
        raise RuntimeError('Запускайте ./bot от обычного пользователя, без sudo. Нужные команды сами запросят sudo.')
    if args.command != 'setup':
        check_service()
    if args.command == 'status':
        run('systemctl', 'status', SERVICE, '--no-pager', '--lines=0')
    elif args.command == 'logs':
        run('sudo', 'journalctl', '-u', SERVICE, '-n', '100', '-f', '--no-pager')
    else:
        with (ROOT / '.bot-control.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Другая сборка или перезапуск уже выполняется.') from None
            run('sudo', '-v')
            if args.command == 'setup':
                setup(args.build)
            else:
                if args.build:
                    build_frontend()
                restart()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(f'Команда {error.cmd[0]} завершилась с кодом {error.returncode}. Дальнейшие шаги остановлены.', file=sys.stderr)
        else:
            print(f'Ошибка: {error}', file=sys.stderr)
        print('Диагностика службы: ./bot status и ./bot logs', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
