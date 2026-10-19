"""
Measures airnefcmd download speed against the simulated camera with WiFi-like latency and throughput.

    uv run tools/bench_download.py <file MB> <round-trip secs> <MB/s, 0 = unthrottled> <chunk KB>...
    uv run tools/bench_download.py 10 0.02 2.5 256 1024 4096
"""
import os, subprocess, sys, tempfile, time, pathlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tests')); sys.path.insert(0, ROOT)
from ptpip_sim import SimCamera, FORMAT_NEF
size_mb, latency, mbps = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
for chunk in sys.argv[4:]:
    cam = SimCamera(latency_secs=latency, bytes_per_sec=mbps*1048576)
    cam.add_folder(0x10000001,'DCIM'); cam.add_folder(0x10000002,'100NIKON',0x10000001)
    cam.add_file(0x20000001,'DSC_0001.NEF',0x10000002,os.urandom(int(size_mb*1048576)),FORMAT_NEF)
    tmp = pathlib.Path(tempfile.mkdtemp()); out = tmp/'out'; out.mkdir()
    env = dict(os.environ, AIRNEF_APPDATA=str(tmp/'ad'))
    t=time.time()
    r = subprocess.run([sys.executable,os.path.join(ROOT, 'airnefcmd.py'),'--ipaddress','127.0.0.1','--port',str(cam.port),'--retrycount','1','--outputdir',str(out),'--maxgetobjtransfersizekb',chunk],env=env,capture_output=True,text=True)
    dt=time.time()-t
    reqs=sum(1 for op,_ in cam.ops_log if op==0x101B)
    print('chunk %6s KB: %6.2fs  %5.2f MB/s  %3d requests  rc=%d'%(chunk,dt,size_mb/dt,reqs,r.returncode)); cam.close()
