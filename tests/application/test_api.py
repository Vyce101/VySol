from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from vysol.server import create_app
from vysol.worlds import WorldStore


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client


def new_world(client, name="Test world"):
    value = {"id": str(uuid4()), "name": name}
    client.app.state.creation.worlds.create(value['id'], name)
    return value


def test_old_empty_world_route_is_retired(client):
    assert client.post('/api/worlds', json={"id": str(uuid4()), "name": "  "}).status_code == 410


def test_settings_persist_and_reject_invalid_speed(client, tmp_path):
    assert client.get('/api/settings').json()['background_speed'] == 'normal'
    assert client.put('/api/settings', json={'background_speed': 'slow'}).status_code == 200
    assert WorldStore(tmp_path).settings()['background_speed'] == 'slow'
    assert client.put('/api/settings', json={'background_speed': 'invalid'}).status_code == 422


def test_origin_host_and_artwork_paths(client):
    assert client.get('/api/worlds', headers={'Origin': 'https://elsewhere.invalid'}).status_code == 403
    assert client.get('/api/worlds', headers={'Host': 'elsewhere.invalid'}).status_code == 403
    assert client.get('/api/worlds/not-an-id/artwork').status_code == 422
    assert client.get(f'/api/worlds/{uuid4()}/artwork').status_code == 404


def test_world_storage_failure_is_user_readable(client, monkeypatch):
    def fail(*args):
        raise OSError('private filesystem details')
    monkeypatch.setattr(WorldStore, 'save_settings', fail)
    response = client.put('/api/settings', json={'background_speed': 'fast'})
    assert response.status_code == 503
    assert 'private' not in response.text


def test_startup_prefers_last_used_world_over_newer_unused_world(client, tmp_path):
    from vysol.worlds import atomic_json
    used = new_world(client, 'Previously used')
    new_world(client, 'New but unused')
    store = WorldStore(tmp_path)
    metadata = store.get(used['id'])
    metadata['last_used_at'] = '2020-01-01T00:00:00+00:00'
    atomic_json(store.directory(used['id']) / 'world.json', metadata)
    assert client.get('/api/worlds').json()[0]['id'] == used['id']


def test_layout_defaults_persistence_and_legacy_settings(client, tmp_path):
    from vysol.worlds import atomic_json
    assert client.get('/api/settings').json() == {'background_speed': 'normal', 'world_layout': 'shelf'}
    atomic_json(tmp_path / 'settings.json', {'background_speed': 'slow'})
    assert client.get('/api/settings').json()['world_layout'] == 'shelf'
    assert client.put('/api/settings', json={'background_speed': 'normal', 'world_layout': 'grid'}).status_code == 200
    assert WorldStore(tmp_path).settings()['world_layout'] == 'grid'
    client.put('/api/settings', json={'background_speed': 'fast'})
    assert WorldStore(tmp_path).settings()['world_layout'] == 'grid'
    assert client.put('/api/settings', json={'background_speed': 'normal', 'world_layout': 'invalid'}).status_code == 422


def test_old_creation_routes_cannot_bypass_processing(client):
    assert client.post('/api/worlds', json={'id': str(uuid4()), 'name': 'World'}).status_code == 410
    assert client.put(f'/api/worlds/{uuid4()}/imports/{uuid4()}', content=b'Book').status_code == 410
