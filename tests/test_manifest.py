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


def test_requires_hermes_floor_matches_the_complete_packaged_plugin_contract():
    # Select exports arrive earlier, but the package also needs unified Desktop
    # discovery, ctx.os, and host.state.connectionId. The last requirement lands
    # in v2026.8.16.2, which ships hermes 0.20.3.
    version_satisfies = pytest.importorskip(
        'hermes_cli.plugins_manifest').version_satisfies

    spec = manifest()['requires_hermes']
    assert version_satisfies(spec, '0.20.3'), 'floor must admit hermes 0.20.3'
    assert not version_satisfies(spec, '0.20.2'), 'floor must exclude hermes 0.20.2'
