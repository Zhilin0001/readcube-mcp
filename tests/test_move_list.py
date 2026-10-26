import json

import httpx
import pytest

from readcube_client import WriteAuthorization
from readcube_client.errors import AuthorizationError, ProtocolError

AUTH = WriteAuthorization(collection_id='library', authorized=True)


def test_move_dry_run_has_no_network(make_client):
    c = make_client(lambda r: pytest.fail('dry-run network'))
    plan = c.move_list('library', 'child', 'parent')
    assert plan.operation == 'move_list' and not plan.verified
    assert plan.body['list']['parent_id'] == 'parent'


def test_move_requires_permission_before_read(make_client):
    c = make_client(lambda r: pytest.fail('unauthorized network'))
    with pytest.raises(AuthorizationError):
        c.move_list('library', 'child', 'parent', dry_run=False)


@pytest.mark.parametrize('parent', ['child', 'descendant', 'foreign'])
def test_move_rejects_cycles_and_foreign_parent(make_client, parent):
    rows = [{'id': 'child', 'name': 'Child'}, {'id': 'descendant', 'parent_id': 'child'}]
    def handler(r):
        assert r.method == 'GET'
        return httpx.Response(200, json={'lists': rows})
    c = make_client(handler, verified=['move_list', 'list_lists'], write_collections=['library'])
    with pytest.raises(ValueError):
        c.move_list('library', 'child', parent, dry_run=False, authorization=AUTH)


def test_move_and_root_preserve_name_and_membership(make_client):
    rows = [{'id': 'child', 'name': 'Child', 'item_ids': ['paper']}, {'id': 'parent', 'name': 'Parent'}]
    requests = []
    def handler(r):
        requests.append(r.method)
        if r.method == 'PATCH':
            patch = json.loads(r.content)['list']
            assert set(patch) == {'id', 'collection_id', 'parent_id'}
            rows[0]['parent_id'] = patch['parent_id']
            return httpx.Response(200, json={'list': rows[0]})
        return httpx.Response(200, json={'lists': rows})
    c = make_client(handler, verified=['move_list', 'list_lists'], write_collections=['library'])
    for parent in ['parent', None]:
        result = c.move_list('library', 'child', parent, dry_run=False, authorization=AUTH)
        assert result['verified'] and result['changed']
        assert result['list']['item_ids'] == ['paper']
    result = c.move_list('library', 'child', None, dry_run=False, authorization=AUTH)
    assert not result['changed']
    assert requests == ['GET', 'PATCH', 'GET', 'GET', 'PATCH', 'GET', 'GET']


def test_move_rejects_unconfirmed_write(make_client):
    rows = [{'id': 'child', 'name': 'Child'}, {'id': 'parent', 'name': 'Parent'}]
    c = make_client(lambda r: httpx.Response(200, json={'lists': rows, 'list': rows[0]}),
                    verified=['move_list', 'list_lists'], write_collections=['library'])
    with pytest.raises(ProtocolError, match='read-back'):
        c.move_list('library', 'child', 'parent', dry_run=False, authorization=AUTH)
