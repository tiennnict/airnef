"""Tests for the GUI <-> airnefcmd link (guilink.py): structured progress, cancel and prompts."""
import os
import subprocess
import sys
import threading
import time

from ptpip_sim import FORMAT_NEF
from test_integration import ROOT, make_camera


class GuiModeProcess:
    """Runs airnefcmd the way the GUI does and collects its @@ protocol lines."""

    def __init__(self, cam, tmp_path, *args):
        self.out = tmp_path / 'out'
        self.out.mkdir(exist_ok=True)
        env = dict(os.environ, AIRNEF_APPDATA=str(tmp_path / 'appdata'), PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        cmd = [sys.executable, str(ROOT / 'airnefcmd.py'), '--guimode', 'yes', '--ipaddress', '127.0.0.1', '--port', str(cam.port),
               '--retrycount', '1', '--outputdir', str(self.out), *args]
        self.proc = subprocess.Popen(cmd, cwd=tmp_path, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        self.lines = []
        self.lock = threading.Lock()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.proc.stdout:
            with self.lock:
                self.lines.append(line.rstrip('\r\n'))

    def snapshot(self):
        with self.lock:
            return list(self.lines)

    def events(self, kind):
        return [l.split('\t')[1:] for l in self.snapshot() if l.startswith('@@' + kind + '\t')]

    def send(self, text):
        self.proc.stdin.write(text + '\n')
        self.proc.stdin.flush()

    def wait_for(self, predicate, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def finish(self, timeout=60):
        rc = self.proc.wait(timeout=timeout)
        self.reader.join(5)
        return rc

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


def test_progress_and_done_events_with_clean_console_output(tmp_path):
    cam = make_camera()
    run = GuiModeProcess(cam, tmp_path)
    try:
        assert run.wait_for(lambda: len(run.events('DONE')) == 3)
        run.finish()                      # stdin stays open, as it does while the GUI is alive
        done = {name: int(size) for name, size, secs in run.events('DONE')}
        assert done == {'DSC_0001.JPG': 300_000, 'DSC_0002.NEF': 2_500_000, 'dsc_0003.jpg': 1_000}
        progress = [(n, int(b), int(t)) for n, b, t in run.events('PROGRESS') if n == 'DSC_0002.NEF']
        assert progress[0][1] == 0 and progress[-1][1] == progress[-1][2] == 2_500_000
        assert all(b1 <= b2 for (_, b1, _), (_, b2, _) in zip(progress, progress[1:]))
        # no console status-line control characters leak into the pipe
        assert not any('\r' in l or '\b' in l for l in run.snapshot())
        assert (run.out / 'DSC_0002.NEF').read_bytes() == cam.objects[0x20000002].data
    finally:
        run.kill()
        cam.close()


def test_cancel_stops_download_cleanly(tmp_path):
    cam = make_camera(bytes_per_sec=1_000_000)   # ~2.5 s for the NEF, so there is time to cancel mid-file
    run = GuiModeProcess(cam, tmp_path, '--extlist', 'NEF', '--maxgetobjtransfersizekb', '256')
    try:
        assert run.wait_for(lambda: any(int(b) > 0 for n, b, t in run.events('PROGRESS')))
        run.send('cancel')
        rc = run.finish(timeout=30)
        assert rc != 0
        assert not (run.out / 'DSC_0002.NEF').exists() and not list(run.out.glob('*.part'))
        assert any('Terminated by user' in l for l in run.snapshot())
        assert 0x1003 in [op for op, _ in cam.ops_log]   # the session was closed with CloseSession
    finally:
        run.kill()
        cam.close()


def test_if_exists_prompt_is_answered_by_the_gui(tmp_path):
    cam = make_camera()
    (tmp_path / 'out').mkdir()
    existing = tmp_path / 'out' / 'DSC_0001.JPG'
    existing.write_bytes(b'old')
    run = GuiModeProcess(cam, tmp_path, '--extlist', 'JPG', '--ifexists', 'prompt')
    try:
        assert run.wait_for(lambda: bool(run.events('PROMPT')))
        question, keys = run.events('PROMPT')[0]
        assert keys.lower() == 'soue' and '(S)kip' in question
        run.send('answer\tS')             # skip
        assert run.finish() == 0
        assert existing.read_bytes() == b'old'
    finally:
        run.kill()
        cam.close()


def test_closing_stdin_cancels_a_running_transfer(tmp_path):
    """If the GUI disappears, airnefcmd must not keep running unseen."""
    cam = make_camera(bytes_per_sec=1_000_000)
    run = GuiModeProcess(cam, tmp_path, '--extlist', 'NEF', '--maxgetobjtransfersizekb', '256')
    try:
        assert run.wait_for(lambda: any(int(b) > 0 for n, b, t in run.events('PROGRESS')))
        run.proc.stdin.close()
        assert run.finish(timeout=30) != 0
        assert not list(run.out.glob('*.part'))
    finally:
        run.kill()
        cam.close()
