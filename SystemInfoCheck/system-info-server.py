#!/usr/bin/env python3
"""
System Info Server — cross-platform (macOS / Linux / Windows)
Serves live hardware, network, battery, CPU, and storage data via HTTP.
"""
import json, subprocess, os, platform, threading, webbrowser, re, socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

PORT = 8765
DIR  = os.path.dirname(os.path.abspath(__file__))
OS   = platform.system()   # 'Darwin' | 'Linux' | 'Windows'

# ── shell helpers ──────────────────────────────────────────────────────────────
def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ''

def run_ps(cmd):
    return run(['powershell', '-NoProfile', '-Command', cmd])

def sp_json(*types):
    out = run(['system_profiler', '-json'] + list(types), timeout=30)
    try:
        return json.loads(out)
    except Exception:
        return {}

def b2gb(b):
    return round(b / 1_000_000_000, 1) if b else 0

def mb2gb(mb):
    return round(mb / 1024, 1) if mb else 0


# ══════════════════════════════════════════════════════════════════════════════
#  macOS
# ══════════════════════════════════════════════════════════════════════════════

def macos_cpu():
    out = run(['top', '-l', '2', '-n', '0', '-s', '1'])
    lines = out.strip().split('\n')
    cpu = {'user': 0, 'sys': 0, 'idle': 100, 'load': [], 'processes': 0, 'threads': 0}
    for line in reversed(lines):
        if 'CPU usage' in line:
            m = re.findall(r'([\d.]+)%', line)
            if len(m) >= 3:
                cpu['user'] = float(m[0])
                cpu['sys']  = float(m[1])
                cpu['idle'] = float(m[2])
            break
    for line in lines:
        if 'Load Avg' in line:
            m = re.findall(r'[\d.]+', line)
            cpu['load'] = [float(x) for x in m[:3]]
        if 'Processes' in line:
            m = re.search(r'(\d+) total', line)
            if m: cpu['processes'] = int(m.group(1))
            m = re.search(r'(\d+) threads', line)
            if m: cpu['threads'] = int(m.group(1))
    return cpu

def macos_memory():
    page_size = 16384
    mem = {'total_gb': 0, 'used_gb': 0, 'free_gb': 0,
           'wired_mb': 0, 'active_mb': 0, 'inactive_mb': 0,
           'compressed_mb': 0, 'pct': 0}
    total_bytes_str = run(['sysctl', '-n', 'hw.memsize']).strip()
    if total_bytes_str:
        total = int(total_bytes_str)
        mem['total_gb'] = round(total / 1e9, 1)

    vm = run(['vm_stat'])
    stats = {}
    for line in vm.split('\n'):
        m = re.match(r'^(.+?):\s+([\d.]+)', line)
        if m:
            stats[m.group(1).strip()] = int(float(m.group(2)))

    def pages_to_mb(k):
        return round(stats.get(k, 0) * page_size / 1_048_576)

    mem['active_mb']     = pages_to_mb('Pages active')
    mem['inactive_mb']   = pages_to_mb('Pages inactive')
    mem['wired_mb']      = pages_to_mb('Pages wired down')
    mem['compressed_mb'] = pages_to_mb('Pages occupied by compressor')
    mem['free_mb']       = pages_to_mb('Pages free')

    used = mem['active_mb'] + mem['wired_mb'] + mem['compressed_mb']
    mem['used_gb'] = round(used / 1024, 1)
    mem['free_gb'] = round(mem['free_mb'] / 1024, 1)
    if mem['total_gb'] > 0:
        mem['pct'] = round(mem['used_gb'] / mem['total_gb'] * 100)
    return mem

def macos_battery():
    d = sp_json('SPPowerDataType')
    bat = {'present': False, 'charge_pct': 0, 'charging': False,
           'fully_charged': False, 'health': '–', 'max_capacity': '–',
           'cycle_count': 0, 'power_source': 'Unknown', 'time_remaining': '–',
           'serial': '–'}

    pmset = run(['pmset', '-g', 'batt'])
    if 'AC Power' in pmset:
        bat['power_source'] = 'AC Power'
    elif 'Battery Power' in pmset:
        bat['power_source'] = 'Battery'
    m = re.search(r'(\d+)%', pmset)
    if m:
        bat['charge_pct'] = int(m.group(1))
        bat['present'] = True
    bat['charging']      = 'charging' in pmset.lower() and 'not charging' not in pmset.lower()
    bat['fully_charged'] = 'charged' in pmset.lower()
    m = re.search(r'(\d+:\d+) remaining', pmset)
    if m: bat['time_remaining'] = m.group(1)

    for entry in (d.get('SPPowerDataType') or []):
        if 'sppower_battery_health_info' in entry:
            hi = entry['sppower_battery_health_info']
            bat['health']       = hi.get('sppower_battery_health', '–')
            bat['max_capacity'] = hi.get('sppower_battery_health_maximum_capacity', '–')
            bat['cycle_count']  = hi.get('sppower_battery_cycle_count', 0)
        if 'sppower_battery_model_info' in entry:
            bat['serial'] = entry['sppower_battery_model_info'].get('sppower_battery_serial_number','–')
    return bat

def macos_wifi():
    d = sp_json('SPAirPortDataType')
    wifi = {'connected': False, 'ssid': '–', 'channel': '–',
            'phy_mode': '–', 'security': '–', 'signal': '–',
            'noise': '–', 'snr': 0, 'country': '–', 'mcs': 0,
            'nearby': []}
    ifaces = (d.get('SPAirPortDataType') or [{}])[0].get('spairport_airport_interfaces', [])
    if not ifaces:
        return wifi
    iface = ifaces[0]
    cur = iface.get('spairport_current_network_information')
    if cur:
        wifi['connected'] = True
        wifi['ssid']      = cur.get('_name', '–')
        wifi['channel']   = cur.get('spairport_network_channel', '–')
        wifi['phy_mode']  = cur.get('spairport_network_phymode', '–')
        wifi['security']  = cur.get('spairport_security_mode', '–').replace('spairport_security_mode_','').replace('_',' ').upper()
        sn = cur.get('spairport_signal_noise', '')
        if '/' in sn:
            parts = sn.split('/')
            wifi['signal'] = parts[0].strip()
            wifi['noise']  = parts[1].strip()
            try:
                sig = int(re.search(r'-?\d+', parts[0]).group())
                noi = int(re.search(r'-?\d+', parts[1]).group())
                wifi['snr'] = sig - noi
            except Exception:
                pass
        wifi['country'] = cur.get('spairport_network_country_code', '–')
        wifi['mcs']     = cur.get('spairport_network_mcs', 0)

    nearby = iface.get('spairport_airport_other_local_wireless_networks', [])
    wifi['nearby'] = [{'ssid': n.get('_name','?'),
                       'channel': n.get('spairport_network_channel','–'),
                       'security': n.get('spairport_security_mode','–').replace('spairport_security_mode_','').replace('_',' ').upper()}
                      for n in nearby[:8]]
    return wifi

def macos_network_interfaces():
    ports, cur = [], {}
    for line in run(['networksetup', '-listallhardwareports']).split('\n'):
        line = line.strip()
        if line.startswith('Hardware Port:'):
            if cur.get('name'):
                ports.append(cur)
            cur = {'name': line[15:]}
        elif line.startswith('Device:'):
            cur['device'] = line[8:]
        elif line.startswith('Ethernet Address:'):
            cur['mac'] = line[18:]
    if cur.get('name'):
        ports.append(cur)

    for p in ports:
        dev = p.get('device', '')
        p['ip']  = run(['ipconfig', 'getifaddr', dev]).strip() or None
        p['ip6'] = run(['ipconfig', 'getifaddr6', dev]).strip() or None
        ifc = run(['ifconfig', dev])
        m = re.search(r'inet (\S+)', ifc)
        if m and not p['ip']: p['ip'] = m.group(1)
        m = re.search(r'mtu (\d+)', ifc)
        p['mtu'] = m.group(1) if m else '–'
        m = re.search(r'status: (\w+)', ifc)
        p['status'] = m.group(1) if m else 'inactive'
    return ports

def macos_connections():
    out = run(['netstat', '-an', '-p', 'tcp'])
    conns, listening = [], []
    for line in out.split('\n')[2:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        proto, local, remote, state = parts[0], parts[3], parts[4], parts[-1]
        if state == 'LISTEN' or remote == '*.*':
            port_m = re.search(r'\.(\d+)$', local)
            if port_m:
                listening.append({'proto': proto, 'port': int(port_m.group(1)), 'addr': local})
        elif state == 'ESTABLISHED':
            conns.append({'proto': proto, 'local': local, 'remote': remote, 'state': state})
    # dedupe listening ports
    seen = set()
    uniq_listen = []
    for l in sorted(listening, key=lambda x: x['port']):
        if l['port'] not in seen:
            seen.add(l['port'])
            uniq_listen.append(l)
    return conns[:30], uniq_listen[:30]

def macos_interface_stats():
    out = run(['netstat', '-ib'])
    stats = []
    for line in out.split('\n')[1:]:
        parts = line.split()
        if len(parts) < 9 or parts[0] == 'Name':
            continue
        name = parts[0]
        if name.endswith('*') or name in ('lo0','gif0','stf0'):
            continue
        try:
            stats.append({'iface': name,
                          'ibytes': int(parts[6]),
                          'obytes': int(parts[9]),
                          'ierrs':  int(parts[5]),
                          'oerrs':  int(parts[8])})
        except (IndexError, ValueError):
            continue
    return stats[:10]

def macos_storage():
    d = sp_json('SPStorageDataType')
    vols = []
    for v in (d.get('SPStorageDataType') or []):
        sz = v.get('size_in_bytes', 0)
        fr = v.get('free_space_in_bytes', 0)
        us = sz - fr
        vols.append({'name':  v.get('_name',''),
                     'mount': v.get('mount_point',''),
                     'fs':    v.get('spStorage_file_system',''),
                     'total': b2gb(sz), 'used': b2gb(us),
                     'free':  b2gb(fr),
                     'pct':   round(us/sz*100) if sz else 0})
    return vols

def macos_displays():
    d = sp_json('SPDisplaysDataType')
    disps = []
    for gpu in (d.get('SPDisplaysDataType') or []):
        gpu_name  = gpu.get('spdisplays_vendor','') or gpu.get('_name','')
        gpu_cores = gpu.get('spdisplays_gmux_gpu_cores','') or ''
        for disp in (gpu.get('spdisplays_ndrvs') or []):
            disps.append({'name':    disp.get('_name',''),
                          'res':     disp.get('_spdisplays_resolution',''),
                          'type':    disp.get('spdisplays_display_type',''),
                          'refresh': disp.get('spdisplays_refresh_rate_current',''),
                          'conn':    disp.get('spdisplays_connection_type',''),
                          'gpu':     gpu_name})
    return disps

def macos_thunderbolt():
    d = sp_json('SPThunderboltDataType')
    tbs = []
    for bus in (d.get('SPThunderboltDataType') or []):
        entry = {'name': bus.get('_name',''), 'speed': 'Up to 120 Gb/s',
                 'status': 'No device connected', 'receptacle': ''}
        port = (bus.get('_items') or [{}])[0] if bus.get('_items') else {}
        entry['receptacle'] = str(port.get('receptacle',''))
        for item in (bus.get('_items') or []):
            name = item.get('thnd_item_name','') or item.get('_name','')
            if name and name != bus.get('_name',''):
                entry['status'] = name
                entry['speed']  = item.get('thnd_spd', entry['speed'])
        tbs.append(entry)
    return tbs

def macos_network_meta():
    gateway, dns_servers, dns_domains = '–', [], []
    route = run(['route', '-n', 'get', 'default'])
    for line in route.split('\n'):
        if 'gateway:' in line:
            gateway = line.split(':',1)[1].strip()
    dns_out = run(['scutil', '--dns'])
    for line in dns_out.split('\n'):
        line = line.strip()
        if re.match(r'nameserver\[\d+\]', line):
            srv = line.split(':',1)[1].strip()
            if srv not in dns_servers:
                dns_servers.append(srv)
        if re.match(r'search domain\[\d+\]', line):
            dom = line.split(':',1)[1].strip()
            if dom not in dns_domains:
                dns_domains.append(dom)
    return {'gateway': gateway, 'dns': dns_servers[:5], 'domains': dns_domains[:5]}

def macos_sysinfo():
    d = sp_json('SPHardwareDataType', 'SPSoftwareDataType')
    hw = (d.get('SPHardwareDataType') or [{}])[0]
    sw = (d.get('SPSoftwareDataType') or [{}])[0]

    cores_str = hw.get('number_processors','')
    perf, eff = 0, 0
    m = re.search(r'proc (\d+):(\d+):(\d+)', cores_str)
    if m:
        perf = int(m.group(2))
        eff  = int(m.group(3))

    gpu_cores = 0
    disp_d = sp_json('SPDisplaysDataType')
    for gpu in (disp_d.get('SPDisplaysDataType') or []):
        c = gpu.get('spdisplays_gmux_gpu_cores','')
        if c:
            try: gpu_cores = int(c)
            except Exception: pass
        if not gpu_cores:
            c2 = gpu.get('spdisplays_total_number_of_cores','')
            try: gpu_cores = int(c2)
            except Exception: pass

    conns, listening = macos_connections()
    net_meta = macos_network_meta()

    return {
        'os': 'macOS',
        'hardware': {
            'model':          hw.get('machine_name',''),
            'model_id':       hw.get('machine_model',''),
            'model_number':   hw.get('model_number',''),
            'chip':           hw.get('chip_type','') or hw.get('cpu_type',''),
            'cores':          cores_str,
            'perf_cores':     perf,
            'eff_cores':      eff,
            'gpu_cores':      gpu_cores,
            'memory':         hw.get('physical_memory',''),
            'serial':         hw.get('serial_number',''),
            'firmware':       hw.get('boot_rom_version',''),
            'platform_uuid':  hw.get('platform_UUID',''),
        },
        'software': {
            'os':     sw.get('os_version',''),
            'kernel': sw.get('kernel_version',''),
            'host':   sw.get('local_host_name',''),
            'user':   sw.get('user_name',''),
            'uptime': sw.get('uptime',''),
            'sip':    sw.get('system_integrity_protection',''),
            'boot':   sw.get('boot_mode','Normal'),
        },
        'cpu':           macos_cpu(),
        'memory_detail': macos_memory(),
        'battery':       macos_battery(),
        'wifi':          macos_wifi(),
        'storage':       macos_storage(),
        'displays':      macos_displays(),
        'ports':         macos_network_interfaces(),
        'iface_stats':   macos_interface_stats(),
        'connections':   conns,
        'listening':     listening,
        'thunderbolt':   macos_thunderbolt(),
        'network_meta':  net_meta,
        'refreshed':     datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Linux
# ══════════════════════════════════════════════════════════════════════════════
def read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return ''

def linux_sysinfo():
    uname = platform.uname()
    # CPU
    cpuinfo = read_file('/proc/cpuinfo')
    cpu_model, cores = '', 0
    for line in cpuinfo.split('\n'):
        if 'model name' in line and not cpu_model:
            cpu_model = line.split(':',1)[1].strip()
        if line.startswith('processor'):
            cores += 1
    # Memory
    meminfo = {}
    for line in read_file('/proc/meminfo').split('\n'):
        if ':' in line:
            k, v = line.split(':', 1)
            meminfo[k.strip()] = int(v.strip().split()[0]) if v.strip() else 0
    total_mb = meminfo.get('MemTotal',0) // 1024
    avail_mb = meminfo.get('MemAvailable',0) // 1024
    used_mb  = total_mb - avail_mb
    # Distro
    pretty = ''
    for line in read_file('/etc/os-release').split('\n'):
        if line.startswith('PRETTY_NAME='):
            pretty = line.split('=',1)[1].strip().strip('"')
    # Uptime
    up_sec = float(read_file('/proc/uptime').split()[0]) if read_file('/proc/uptime') else 0
    h, rem = divmod(int(up_sec), 3600)
    m = rem // 60
    # Load
    load = [float(x) for x in read_file('/proc/loadavg').split()[:3]] if read_file('/proc/loadavg') else []
    # Storage
    out = run(['df', '-B1', '--output=source,size,used,avail,pcent,target'])
    vols = []
    for line in out.split('\n')[1:]:
        parts = line.split()
        if len(parts) < 6 or not parts[0].startswith('/dev/'): continue
        sz = int(parts[1]); us = int(parts[2]); fr = int(parts[3])
        pct = int(parts[4].replace('%','')) if '%' in parts[4] else 0
        vols.append({'name': parts[0], 'mount': parts[5], 'fs': '',
                     'total': b2gb(sz), 'used': b2gb(us), 'free': b2gb(fr), 'pct': pct})
    # Network
    ports = []
    ip_out = run(['ip', '-o', 'link', 'show'])
    for line in ip_out.split('\n'):
        m = re.match(r'\d+: (\S+?)[@:]', line)
        if not m: continue
        dev = m.group(1)
        if dev == 'lo': continue
        mac_m = re.search(r'link/\S+ ([0-9a-f:]{17})', line)
        mac = mac_m.group(1) if mac_m else ''
        ip_out2 = run(['ip', '-o', '-4', 'addr', 'show', dev])
        ip_m = re.search(r'inet (\S+)/', ip_out2)
        ip_addr = ip_m.group(1) if ip_m else None
        state = 'active' if 'state UP' in line else 'inactive'
        ports.append({'name': dev, 'device': dev, 'mac': mac, 'ip': ip_addr,
                      'status': state, 'mtu': '1500'})
    # Displays
    disps = []
    xrandr = run(['xrandr', '--query']) if os.environ.get('DISPLAY') else ''
    for line in xrandr.split('\n'):
        if ' connected' in line:
            parts = line.split()
            res = next((p for p in parts if re.match(r'\d+x\d+', p)), '–')
            disps.append({'name': parts[0], 'res': res, 'type': 'External', 'refresh': '', 'gpu': ''})

    return {
        'os': 'Linux',
        'hardware': {'model': platform.node(), 'model_id': uname.machine,
                     'chip': cpu_model, 'cores': str(cores),
                     'perf_cores': cores, 'eff_cores': 0, 'gpu_cores': 0,
                     'memory': f'{round(total_mb/1024,1)} GB',
                     'serial': read_file('/sys/class/dmi/id/product_serial') or '–',
                     'firmware': read_file('/sys/class/dmi/id/bios_version') or '–',
                     'platform_uuid': '', 'model_number': ''},
        'software': {'os': pretty or uname.system, 'kernel': uname.release,
                     'host': uname.node, 'user': os.environ.get('USER','–'),
                     'uptime': f'{h}h {m}m', 'sip': '–', 'boot': 'Normal'},
        'cpu': {'user': 0, 'sys': 0, 'idle': 100, 'load': load, 'processes': 0, 'threads': 0},
        'memory_detail': {'total_gb': round(total_mb/1024,1), 'used_gb': round(used_mb/1024,1),
                          'free_gb': round(avail_mb/1024,1), 'wired_mb': 0,
                          'active_mb': used_mb, 'inactive_mb': 0,
                          'compressed_mb': 0, 'free_mb': avail_mb,
                          'pct': round(used_mb/total_mb*100) if total_mb else 0},
        'battery': {'present': False},
        'wifi': {'connected': False},
        'storage': vols, 'displays': disps,
        'ports': ports, 'iface_stats': [], 'connections': [], 'listening': [],
        'thunderbolt': [], 'network_meta': {'gateway':'–','dns':[],'domains':[]},
        'refreshed': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Windows
# ══════════════════════════════════════════════════════════════════════════════
def windows_sysinfo():
    def sjson(s):
        try:
            r = json.loads(s)
            return r if isinstance(r, list) else [r]
        except Exception:
            return [{}]

    cs   = sjson(run_ps('Get-CimInstance Win32_ComputerSystem | ConvertTo-Json'))[0]
    os_d = sjson(run_ps('Get-CimInstance Win32_OperatingSystem | ConvertTo-Json'))[0]
    cpu  = sjson(run_ps('Get-CimInstance Win32_Processor | ConvertTo-Json'))[0]
    bio  = sjson(run_ps('Get-CimInstance Win32_BIOS | ConvertTo-Json'))[0]
    disks = sjson(run_ps('Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ConvertTo-Json'))
    disps = sjson(run_ps('Get-CimInstance Win32_VideoController | ConvertTo-Json'))
    nets  = sjson(run_ps('Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=True" | ConvertTo-Json'))
    bat   = sjson(run_ps('Get-CimInstance Win32_Battery | ConvertTo-Json'))[0]

    total_ram = round(int(cs.get('TotalPhysicalMemory', 0)) / 1e9, 1)
    free_ram  = round(int(os_d.get('FreePhysicalMemory', 0)) / 1e6, 1)
    used_ram  = round(total_ram - free_ram, 1)

    vols = []
    for d in disks:
        sz = int(d.get('Size', 0)); fr = int(d.get('FreeSpace', 0)); us = sz - fr
        vols.append({'name': d.get('Name',''), 'mount': d.get('Name',''), 'fs': d.get('FileSystem',''),
                     'total': b2gb(sz), 'used': b2gb(us), 'free': b2gb(fr),
                     'pct': round(us/sz*100) if sz else 0})

    displays = [{'name': d.get('Name',''),
                 'res':  f"{d.get('CurrentHorizontalResolution','?')} × {d.get('CurrentVerticalResolution','?')}",
                 'type': d.get('VideoProcessor',''), 'refresh': str(d.get('CurrentRefreshRate',''))+'Hz',
                 'gpu': '', 'conn': ''} for d in disps]

    ports = [{'name': n.get('Description',''), 'device': str(n.get('InterfaceIndex','')),
              'mac': n.get('MACAddress',''), 'ip': (n.get('IPAddress') or [None])[0],
              'status': 'active', 'mtu': '1500'} for n in nets]

    bat_charge = bat.get('EstimatedChargeRemaining', 0) if bat else 0

    return {
        'os': 'Windows',
        'hardware': {'model': cs.get('Model',''), 'model_id': cs.get('SystemFamily',''),
                     'model_number': '', 'chip': cpu.get('Name',''),
                     'cores': str(cpu.get('NumberOfLogicalProcessors','')),
                     'perf_cores': 0, 'eff_cores': 0, 'gpu_cores': 0,
                     'memory': f'{total_ram} GB', 'serial': bio.get('SerialNumber',''),
                     'firmware': bio.get('SMBIOSBIOSVersion',''), 'platform_uuid': ''},
        'software': {'os': os_d.get('Caption',''), 'kernel': os_d.get('Version',''),
                     'host': cs.get('DNSHostName',''), 'user': cs.get('UserName',''),
                     'uptime': '–', 'sip': '–', 'boot': 'Normal'},
        'cpu': {'user': 0, 'sys': 0, 'idle': 100, 'load': [], 'processes': 0, 'threads': 0},
        'memory_detail': {'total_gb': total_ram, 'used_gb': used_ram, 'free_gb': free_ram,
                          'wired_mb': 0, 'active_mb': 0, 'inactive_mb': 0,
                          'compressed_mb': 0, 'free_mb': int(free_ram*1024),
                          'pct': round(used_ram/total_ram*100) if total_ram else 0},
        'battery': {'present': bool(bat), 'charge_pct': bat_charge,
                    'power_source': 'AC' if bat.get('BatteryStatus') == 2 else 'Battery'},
        'wifi': {'connected': False},
        'storage': vols, 'displays': displays,
        'ports': ports, 'iface_stats': [], 'connections': [], 'listening': [],
        'thunderbolt': [], 'network_meta': {'gateway':'–','dns':[],'domains':[]},
        'refreshed': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Speed test  (macOS networkQuality)
# ══════════════════════════════════════════════════════════════════════════════
def run_speedtest():
    try:
        out = subprocess.run(
            ['networkQuality', '-c', '-s'],
            capture_output=True, text=True, timeout=60
        ).stdout.strip()
        # last non-empty line is the JSON summary
        for line in reversed(out.split('\n')):
            line = line.strip()
            if line.startswith('{'):
                data = json.loads(line)
                dl = data.get('dl_throughput', 0)
                ul = data.get('ul_throughput', 0)
                return {
                    'dl_mbps':      round(dl / 1_000_000, 1),
                    'ul_mbps':      round(ul / 1_000_000, 1),
                    'responsiveness': data.get('responsiveness', 0),
                    'base_rtt_ms':  data.get('base_rtt', 0),
                    'error': None,
                }
        return {'error': 'No result parsed', 'dl_mbps': 0, 'ul_mbps': 0}
    except subprocess.TimeoutExpired:
        return {'error': 'Timeout', 'dl_mbps': 0, 'ul_mbps': 0}
    except FileNotFoundError:
        return {'error': 'networkQuality not available', 'dl_mbps': 0, 'ul_mbps': 0}
    except Exception as e:
        return {'error': str(e), 'dl_mbps': 0, 'ul_mbps': 0}


# ══════════════════════════════════════════════════════════════════════════════
#  Dispatcher
# ══════════════════════════════════════════════════════════════════════════════
def sysinfo():
    if OS == 'Darwin':
        return macos_sysinfo()
    elif OS == 'Linux':
        return linux_sysinfo()
    elif OS == 'Windows':
        return windows_sysinfo()
    return {'os': OS, 'error': f'Unsupported: {OS}',
            'refreshed': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}


# ══════════════════════════════════════════════════════════════════════════════
#  HTTP server
# ══════════════════════════════════════════════════════════════════════════════
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/api/sysinfo':
            self.send_json(sysinfo())
        elif path == '/api/speedtest':
            self.send_json(run_speedtest())
        elif path in ('/', '/system-info.html'):
            html_path = os.path.join(DIR, 'system-info.html')
            with open(html_path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(data))
            self.end_headers()
            self.wfile.write(data)
        elif path == '/readme':
            html_path = os.path.join(DIR, 'readme.html')
            with open(html_path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(data))
            self.end_headers()
            self.wfile.write(data)
        elif path == '/api/readme':
            readme_path = os.path.join(DIR, 'README.md')
            with open(readme_path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', len(data))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

if __name__ == '__main__':
    server = HTTPServer(('localhost', PORT), Handler)
    url = f'http://localhost:{PORT}'
    print(f'[{OS}] System Info Dashboard → {url}')
    print('Endpoints:')
    print(f'  GET /             → dashboard UI')
    print(f'  GET /readme       → README documentation')
    print(f'  GET /api/sysinfo  → live system data (JSON)')
    print(f'  GET /api/readme   → README.md raw text')
    print(f'  GET /api/speedtest → run network speed test (takes ~30s)')
    print('Press Ctrl+C to stop.')
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
