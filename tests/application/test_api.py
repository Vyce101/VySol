from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from vysol.books import ImportLimits
from vysol.server import create_app
from vysol.worlds import WorldStore


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client


def new_world(client, name="Test world"):
    value = {"id": str(uuid4()), "name": name}
    assert client.post('/api/worlds', json=value).status_code == 200
    return value


def test_worlds_persist_and_submissions_are_idempotent(client, tmp_path):
    world = new_world(client)
    client.post('/api/worlds', json=world)
    new_world(client)
    assert len(client.get('/api/worlds').json()) == 2
    assert len(WorldStore(tmp_path).list_worlds()) == 2
    assert client.get(f"/api/worlds/{world['id']}/books").json() == []


def test_blank_world_name_is_rejected(client):
    assert client.post('/api/worlds', json={"id": str(uuid4()), "name": "  "}).status_code == 422


def test_imports_partial_failures_and_exact_reconciliation(client):
    world = new_world(client)
    first, second = str(uuid4()), str(uuid4())
    path = f"/api/worlds/{world['id']}/imports/"
    assert client.get(path + first).json()['status'] == 'unknown'
    good = client.put(path + first, content=b'Valid text', headers={'X-Filename': 'Good.txt'}).json()
    assert good['book_id'] and good['error'] is None
    assert client.get(path + first).json() == good
    assert client.put(path + first, content=b'Valid text', headers={'X-Filename': 'Good.txt'}).json() == good
    bad = client.put(path + second, content=b'\xff', headers={'X-Filename': 'Bad.txt'}).json()
    assert bad['error'] == 'invalid_encoding'
    retry = client.put(path + str(uuid4()), content=b'Valid replacement', headers={'X-Filename': 'Bad.txt'}).json()
    assert retry['error'] is None
    books = client.get(f"/api/worlds/{world['id']}/books").json()
    assert len(books) == 2
    assert all('path' not in key for record in books for key in record)


def test_duplicate_filename_is_error(client):
    world = new_world(client)
    path = f"/api/worlds/{world['id']}/imports/"
    for filename in ('Book.txt', 'book.TXT'):
        response = client.put(path + str(uuid4()), content=b'Text', headers={'X-Filename': filename})
    assert response.json()['error'] == 'duplicate_name'


def test_upload_limit_applies_to_stream(tmp_path):
    with TestClient(create_app(tmp_path, limits=ImportLimits(max_upload_bytes=3))) as client:
        world = new_world(client)
        response = client.put(f"/api/worlds/{world['id']}/imports/{uuid4()}", content=iter([b'ab', b'cd']), headers={'X-Filename': 'Book.txt'})
        assert response.status_code == 413
        assert client.get(f"/api/worlds/{world['id']}/books").json() == []


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

def test_reconcile_interrupted_receipt_requires_matching_original(client, tmp_path):
    import hashlib
    from vysol.worlds import atomic_json
    world = new_world(client)
    store = WorldStore(tmp_path)
    prefix = f"/api/worlds/{world['id']}/imports/"
    result = client.put(prefix + str(uuid4()), content=b'Original', headers={'X-Filename': 'Story.txt'}).json()
    operation = str(uuid4())
    receipt = store.directory(world['id']) / 'imports' / f'{operation}.json'
    pending = {'status': 'pending', 'filename': 'Story.txt', 'comparison_name': 'story', 'content_digest': hashlib.sha256(b'Other').hexdigest()}
    atomic_json(receipt, pending)
    assert client.get(prefix + operation).json()['status'] == 'unknown'
    pending['content_digest'] = hashlib.sha256(b'Original').hexdigest()
    atomic_json(receipt, pending)
    recovered = client.get(prefix + operation).json()
    assert recovered['book_id'] == result['book_id']
    assert recovered['error'] is None

def test_concurrent_submissions_keep_one_world_and_one_book(client):
    from concurrent.futures import ThreadPoolExecutor
    value = {'id': str(uuid4()), 'name': 'Concurrent world'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post('/api/worlds', json=value), range(2)))
    assert all(response.status_code == 200 for response in responses)
    assert len(client.get('/api/worlds').json()) == 1
    def send(_):
        return client.put(f"/api/worlds/{value['id']}/imports/{uuid4()}", content=b'Text', headers={'X-Filename':'Same.txt'}).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, range(2)))
    assert sum(result['error'] is None for result in results) == 1
    assert sum(result['error'] == 'duplicate_name' for result in results) == 1

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
