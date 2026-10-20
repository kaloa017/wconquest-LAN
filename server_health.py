"""Bounded, read-only host telemetry. No shell, credentials or public endpoints."""
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import urlopen

STARTED = time.monotonic()
_lock = threading.Lock()
_cached = None
_cpu = None


def read(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=1,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return result.stdout.strip()[:4096] if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def throttle_flags(value):
    labels = ('Undervoltage', 'CPU frequency capped', 'Throttling', 'Temperature limit')
    return {'raw': hex(value), 'current': [name for bit, name in enumerate(labels) if value & (1 << bit)],
            'since_boot': [name for bit, name in enumerate(labels) if value & (1 << (bit + 16))]}


def memory_linux(text):
    values = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in text.splitlines() if ':' in line}
    total = values.get('MemTotal', 0)
    available = values.get('MemAvailable', values.get('MemFree', 0))
    swap = values.get('SwapTotal', 0)
    return dict(total=total, available=available, used=total-available,
                percent=round(100*(total-available)/total, 1) if total else None,
                swap_total=swap, swap_used=swap-values.get('SwapFree', 0))


def windows_stats():
    import ctypes
    from ctypes import wintypes
    class Memory(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong) for name in ('total', 'available', 'page_total', 'page_free', 'virtual_total', 'virtual_free', 'extended')]
    data = Memory(); data.length = ctypes.sizeof(data)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(data)):
        return None, None
    ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    return dict(total=data.total, available=data.available, used=data.total-data.available,
                percent=data.load, swap_total=None, swap_used=None), ctypes.windll.kernel32.GetTickCount64()/1000


def collect(data_directory):
    global _cpu
    result = dict(sampled_at=int(time.time()), platform=platform.system(), kernel=platform.release(),
                  architecture=platform.machine(), model=read('/proc/device-tree/model'),
                  cpu_cores=os.cpu_count(), process_uptime_seconds=int(time.monotonic()-STARTED),
                  uptime_seconds=None, cpu_percent=None, load=None, memory=None,
                  temperature_c=None, temperature_source=None, cpu_mhz=None, fan_rpm=None,
                  throttle=None, process_memory_bytes=None, network=[], services=[], tunnel=None)
    if result['model']:result['model']=result['model'].rstrip('\0')
    if platform.system() == 'Linux':
        uptime=read('/proc/uptime')
        if uptime:result['uptime_seconds']=float(uptime.split()[0])
        memory=read('/proc/meminfo')
        if memory:result['memory']=memory_linux(memory)
        stats=read('/proc/stat')
        if stats:
            ticks=list(map(int,stats.splitlines()[0].split()[1:9]));total=sum(ticks);idle=ticks[3]+ticks[4]
            if _cpu and total>_cpu[0]:result['cpu_percent']=round(100*(1-(idle-_cpu[1])/(total-_cpu[0])),1)
            _cpu=(total,idle)
        try:result['load']=list(os.getloadavg())
        except OSError:pass
        status=read('/proc/self/status') or ''
        for line in status.splitlines():
            if line.startswith('VmRSS:'):result['process_memory_bytes']=int(line.split()[1])*1024
        frequency=read('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq')
        if frequency and frequency.isdigit():result['cpu_mhz']=int(frequency)/1000
        temperature=read('/sys/class/thermal/thermal_zone0/temp')
        if temperature:
            try:result['temperature_c']=float(temperature)/1000;result['temperature_source']='Linux thermal sensor'
            except ValueError:pass
        for fan in Path('/sys/class/hwmon').glob('hwmon*/fan1_input'):
            rpm=read(fan)
            if rpm and rpm.isdigit():result['fan_rpm']=int(rpm);break
        if 'Raspberry Pi' in (result['model'] or ''):
            tool=shutil.which('vcgencmd')
            if tool:
                measured=command([tool,'measure_temp'])
                if measured:
                    try:result['temperature_c']=float(measured.split('=')[1].split("'")[0]);result['temperature_source']='Pi firmware'
                    except (ValueError,IndexError):pass
                flags=command([tool,'get_throttled'])
                if flags:
                    try:result['throttle']=throttle_flags(int(flags.split('=')[1],16))
                    except (ValueError,IndexError):pass
        for line in (read('/proc/net/dev') or '').splitlines():
            if ':' not in line:continue
            interface,values=line.split(':',1);values=values.split()
            if len(values)>=16 and interface.strip()!='lo':
                result['network'].append(dict(interface=interface.strip(),received=int(values[0]),sent=int(values[8]),
                    receive_errors=int(values[2]),send_errors=int(values[10]),receive_drops=int(values[3]),send_drops=int(values[11])))
        tool=shutil.which('systemctl')
        if tool:
            # One bounded command for fixed service names; never show ExecStart or environment.
            names=['wconquest.service','wconquest-tunnel.service','wconquest-backup.timer','wconquest-backup.service']
            output=command([tool,'show',*names,'--property=Id,LoadState,ActiveState,SubState,NRestarts,Result,LastTriggerUSec,NextElapseUSecRealtime'])
            for section in (output or '').split('\n\n'):
                fields=dict(line.split('=',1) for line in section.splitlines() if '=' in line)
                if fields.get('Id') in names:result['services'].append(fields)
        try:
            with urlopen('http://127.0.0.1:20241/ready',timeout=.6) as response:result['tunnel']=response.status==200
        except Exception:result['tunnel']=False
    elif platform.system()=='Windows':
        try:result['memory'],result['uptime_seconds']=windows_stats()
        except (OSError,AttributeError):pass
    disk=shutil.disk_usage(data_directory)
    result['disk']=dict(total=disk.total,used=disk.used,free=disk.free,percent=round(100*disk.used/disk.total,1))
    result['threads']=threading.active_count()
    result['warnings']=[]
    if result['disk']['percent']>=90:result['warnings'].append('Storage is at least 90% full.')
    if result['memory'] and result['memory']['percent']>=90:result['warnings'].append('Memory use is at least 90%.')
    if result['temperature_c'] is not None and result['temperature_c']>=80:result['warnings'].append('CPU temperature is high; inspect cooling.')
    if result['throttle'] and result['throttle']['current']:result['warnings'].append('Pi power or throttling warning is currently active.')
    if result['tunnel'] is False:result['warnings'].append('Local tunnel readiness check failed or no tunnel is running.')
    result['unavailable_note']='Unavailable means the OS, sensor or service account does not expose that metric. Hardware failures and school network reachability cannot be fully diagnosed here.'
    return result


def snapshot(data_directory):
    global _cached
    with _lock:
        identity=str(data_directory)
        if not _cached or _cached[0]!=identity or time.monotonic()-_cached[1]>=10:
            _cached=(identity,time.monotonic(),collect(data_directory))
        return _cached[2]
