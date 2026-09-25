"""The manifest's requires_hermes gate must admit the Hermes it ships against.

`hermes plugins validate` only checks that the spec parses, so a spec naming the
SDK release-date tag (v2026.7.20) instead of the distribution version (0.19.0)
passes validation while making the plugin silently unloadable.
"""
import pathlib

import yaml

MANIFEST = pathlib.Path(__file__).resolve().parent.parent / 'plugin.yaml'


def manifest():
    return yaml.safe_load(MANIFEST.read_text())


def test_requires_hermes_is_declared():
    spec = manifest().get('requires_hermes')
    assert spec, 'plugin.yaml must declare requires_hermes'
    assert spec.startswith('>='), f'unexpected spec form: {spec!r}'


def test_requires_hermes_admits_the_running_hermes():
    from hermes_cli.plugins_manifest import version_satisfies
    import hermes_cli

    running = hermes_cli.__version__
    spec = manifest()['requires_hermes']
    assert version_satisfies(spec, running), (
        f'requires_hermes {spec!r} rejects the running hermes {running!r}; '
        'the loader compares the distribution version, not the release-date tag'
    )


def test_requires_hermes_floor_matches_the_complete_packaged_plugin_contract():
    # Backend discovery and profile-scoped routes arrive in v2026.9.14.
    # test_backend_compatibility.py executes the pinned release, including the
    # Codex 401 path (whose resolver has no force_refresh keyword at this floor).
    from hermes_cli.plugins_manifest import version_satisfies

    spec = manifest()['requires_hermes']
    assert version_satisfies(spec, '0.21.3'), 'floor must admit hermes 0.21.3'
    for unsupported in ('0.19.0', '0.20.3', '0.21.2'):
        assert not version_satisfies(spec, unsupported), f'floor must exclude hermes {unsupported}'
