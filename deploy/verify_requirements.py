"""Verify a prepared virtualenv before deploying changed, fully pinned requirements."""
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def mismatches(requirements):
    errors = []
    for line in requirements.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)', line)
        if not match:
            errors.append(f'Unsupported requirement: {line}')
            continue
        name, expected = match.groups()
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = 'missing'
        if installed != expected:
            errors.append(f'{name}: installed {installed}, required {expected}')
    return errors


if __name__ == '__main__':
    if sys.prefix == sys.base_prefix:
        raise SystemExit('Use the project virtualenv.')
    errors = mismatches(Path(sys.argv[1]).read_text())
    if errors:
        raise SystemExit('\n'.join(errors) + '\nPrepare the server virtualenv before deploying.')
    print('Prepared virtualenv matches every pinned release requirement.')
