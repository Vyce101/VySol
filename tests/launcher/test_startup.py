"""Launcher failure paths must close the job and never open a premature browser."""
import importlib.util
from pathlib import Path
import socket
import sys
import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows launcher')

@pytest.fixture
def launcher(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path('launcher').resolve()))
    spec = importlib.util.spec_from_file_location('vysol_launcher', Path('launcher/start.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('VYSOL_DATA_DIR', str(tmp_path))
    return module


def test_occupied_port_reports_error_and_closes_job(launcher, monkeypatch, capsys):
    class Job:
        closed = False
        def close(self): self.closed = True
    job = Job()
    monkeypatch.setattr(launcher, 'ProcessJob', lambda: job)
    monkeypatch.setattr(launcher.webbrowser, 'open', lambda _: pytest.fail('Browser opened before readiness'))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        monkeypatch.setenv('VYSOL_PORT', str(listener.getsockname()[1]))
        launcher.run()
    assert job.closed
    assert 'already in use' in capsys.readouterr().out


def test_missing_tooling_stops_cleanly(launcher, monkeypatch, capsys):
    class Job:
        closed = False
        def close(self): self.closed = True
    job = Job()
    monkeypatch.setenv('VYSOL_PORT', '0')
    monkeypatch.setattr(launcher, 'ProcessJob', lambda: job)
    monkeypatch.setattr(launcher.shutil, 'which', lambda _: None)
    launcher.run()
    assert job.closed
    assert 'Install Python' in capsys.readouterr().out
