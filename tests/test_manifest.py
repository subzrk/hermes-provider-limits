"""The manifest's requires_hermes gate must admit the Hermes it ships against.

`hermes plugins validate` only checks that the spec parses, so a spec naming the
SDK release-date tag (v2026.7.20) instead of the distribution version (0.19.0)
passes validation while making the plugin silently unloadable.
"""
import pathlib

import pytest
import yaml

MANIFEST = pathlib.Path(__file__).resolve().parent.parent / 'plugin.yaml'


def manifest():
    return yaml.safe_load(MANIFEST.read_text())


def test_requires_hermes_is_declared():
    spec = manifest().get('requires_hermes')
    assert spec, 'plugin.yaml must declare requires_hermes'
    assert spec.startswith('>='), f'unexpected spec form: {spec!r}'


def test_requires_hermes_admits_the_running_hermes():
    version_satisfies = pytest.importorskip(
        'hermes_cli.plugins_manifest').version_satisfies
    import hermes_cli

    running = hermes_cli.__version__
    spec = manifest()['requires_hermes']
    assert version_satisfies(spec, running), (
        f'requires_hermes {spec!r} rejects the running hermes {running!r}; '
        'the loader compares the distribution version, not the release-date tag'
    )


def test_requires_hermes_floor_matches_the_sdk_release_that_added_select():
    # The v2026.7.20 release is the first whose plugin SDK exports the Select
    # primitives this page renders; it ships hermes 0.19.0.
    version_satisfies = pytest.importorskip(
        'hermes_cli.plugins_manifest').version_satisfies

    spec = manifest()['requires_hermes']
    assert version_satisfies(spec, '0.19.0'), 'floor must admit hermes 0.19.0'
    assert not version_satisfies(spec, '0.18.0'), 'floor must exclude hermes 0.18.0'
