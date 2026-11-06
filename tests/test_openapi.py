import re
from pathlib import Path

import yaml
from openapi_spec_validator import validate

SPEC_PATH = Path(__file__).resolve().parent.parent / 'openapi.yaml'
HTTP_METHODS = {'get', 'post', 'put', 'patch', 'delete'}


def load_spec():
    return yaml.safe_load(SPEC_PATH.read_text(encoding='utf-8'))


def spec_operations(spec):
    return {(m.upper(), path) for path, item in spec['paths'].items() for m in item if m in HTTP_METHODS}


def flask_operations(app):
    ops = set()
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith('/api/'):
            path = re.sub(r'<(?:\w+:)?(\w+)>', r'{\1}', rule.rule)
            ops.update((m, path) for m in rule.methods - {'HEAD', 'OPTIONS'})
    return ops


def test_spec_is_valid_openapi_3():
    spec = load_spec()
    assert spec['openapi'].startswith('3.0')
    validate(spec)


def test_spec_documents_every_route_and_nothing_else(app):
    assert spec_operations(load_spec()) == flask_operations(app)


def test_fourteen_operations_twelve_of_them_role_restricted():
    spec = load_spec()
    operations = [op for item in spec['paths'].values() for m, op in item.items() if m in HTTP_METHODS]
    restricted = [op for op in operations if op.get('security')]
    assert len(operations) == 14
    assert len(restricted) == 12
    assert {op['tags'][0] for op in restricted} == {'Admin', 'Staff', 'Trekker'}
    assert sum(1 for op in restricted if op['tags'][0] == 'Admin') == 6
    assert sum(1 for op in restricted if op['tags'][0] == 'Staff') == 3
    assert sum(1 for op in restricted if op['tags'][0] == 'Trekker') == 3


def test_restricted_operations_document_401_and_403():
    spec = load_spec()
    for path, item in spec['paths'].items():
        for method, op in item.items():
            if method in HTTP_METHODS and op.get('security'):
                assert {'401', '403'} <= set(op['responses']), f'{method} {path}'


def test_spec_security_matches_what_the_api_really_does(anon, world):
    # a restricted operation must answer 401 to an anonymous caller, a public one must not,
    # and whatever comes back must be a status the spec documents
    spec = load_spec()
    for path, item in spec['paths'].items():
        for method, op in item.items():
            if method not in HTTP_METHODS:
                continue
            url = re.sub(r'\{\w+\}', '1', path)
            resp = anon.open(url, method=method.upper(), json={})
            if op.get('security'):
                assert resp.status_code == 401, f'{method} {path} should need a login'
            else:
                assert resp.status_code != 401, f'{method} {path} should be public'
            assert str(resp.status_code) in op['responses'], f'{method} {path} -> {resp.status_code} undocumented'
