"""Required integration gate against pinned, real Hermes release source.

Set HERMES_SOURCE_REPO to a git clone containing the three commits below.
No network, editable host imports, mocked Hermes modules, or skipped coverage.
"""
import os
from pathlib import Path
import site
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASES = [
    ('0.20.3', 'v2026.8.16.2', '7339f5f160db5c96657a3bab60151227cc61f66c', 'reject'),
    ('0.21.2', 'v2026.9.11', '939e45c91d751fadd94dcd1b873ac3cb44846213', 'reject'),
    ('0.21.3', 'v2026.9.14', '345cd2b057a452236de401d3534b8502a7465e8d', 'support'),
]


@pytest.mark.parametrize('version,tag,commit,mode', RELEASES)
def test_real_release_backend_contract(tmp_path, version, tag, commit, mode):
    source = os.environ.get('HERMES_SOURCE_REPO')
    assert source, 'Set HERMES_SOURCE_REPO to a Hermes git clone; real-release coverage is required'
    resolved = subprocess.check_output(['git', '-C', source, 'rev-parse', commit + '^{commit}'], text=True).strip()
    assert resolved == commit
    archive = tmp_path / 'release.tar'
    with archive.open('wb') as output:
        subprocess.run(['git', '-C', source, 'archive', commit], stdout=output, check=True)
    release = tmp_path / 'release'
    release.mkdir()
    with tarfile.open(archive) as bundle:
        bundle.extractall(release, filter='data')
    home = tmp_path / 'home'
    profile = home / '.hermes'
    profile.mkdir(parents=True)
    env = {'HOME': str(home), 'HERMES_HOME': str(profile),
           'PATH': os.defpath, 'PYTHONIOENCODING': 'utf-8',
           'TMPDIR': str(tmp_path), 'XDG_CONFIG_HOME': str(home / '.config')}
    result = subprocess.run(
        [sys.executable, '-I', '-S', str(ROOT / 'tests/probe_hermes_release.py'),
         str(release), str(ROOT), mode, *site.getsitepackages()],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=120,
    )
    assert result.returncode == 0, f'{tag} ({commit})\n{result.stdout}\n{result.stderr}'
    assert f'"version": "{version}"' in result.stdout
    print(result.stdout)
