"""Exercise Windows process ownership without touching unrelated processes."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import time
import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows process lifecycle')


def test_job_closure_terminates_child_and_descendant(tmp_path):
    spec = importlib.util.spec_from_file_location('windows_job', Path('launcher/windows_job.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    marker = tmp_path / 'descendant.txt'
    script = 'import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(120)"]); Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(120)'
    job = module.ProcessJob()
    child = job.spawn([sys.executable, '-c', script, str(marker)])
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert marker.exists()
        pid = int(marker.read_text())
        kernel = module.kernel
        kernel.OpenProcess.restype = module.wintypes.HANDLE
        descendant = kernel.OpenProcess(0x100000, False, pid)
        assert descendant
        kernel.WaitForSingleObject.argtypes = [module.wintypes.HANDLE, module.wintypes.DWORD]
        job.close()
        child.wait(timeout=10)
        assert kernel.WaitForSingleObject(descendant, 10000) == 0
        kernel.CloseHandle(descendant)
    finally:
        job.close()


def test_abrupt_supervisor_exit_kills_owned_process(tmp_path):
    spec = importlib.util.spec_from_file_location('windows_job', Path('launcher/windows_job.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    marker = tmp_path / 'child.txt'
    script = ('import sys,time; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
              'from windows_job import ProcessJob; job=ProcessJob(); '
              'p=job.spawn([sys.executable,"-c","import time; time.sleep(120)"]); '
              'Path(sys.argv[2]).write_text(str(p.pid)); time.sleep(120)')
    supervisor = subprocess.Popen([sys.executable, '-c', script, str(Path('launcher').resolve()), str(marker)])
    handle = None
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert marker.exists()
        module.kernel.OpenProcess.restype = module.wintypes.HANDLE
        handle = module.kernel.OpenProcess(0x100000, False, int(marker.read_text()))
        assert handle
        module.kernel.WaitForSingleObject.argtypes = [module.wintypes.HANDLE, module.wintypes.DWORD]
        supervisor.kill()
        supervisor.wait(timeout=10)
        assert module.kernel.WaitForSingleObject(handle, 10000) == 0
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait()
        if handle:
            module.kernel.CloseHandle(handle)
