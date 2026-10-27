"""Optional systemd user receiving. No shell-start or agent scheduler fallback."""
import subprocess
import sys

from .io import atomic, digest, load, no_links, read, require, source_lock, write_json


def systemctl(*arguments):
    try:
        result = subprocess.run(['systemctl','--user',*arguments],capture_output=True,text=True,timeout=15)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise ValueError('systemd user manager unavailable; manual agents sync remains available') from exc
    require(result.returncode == 0, 'systemd user action failed; manual sync remains available: ' + result.stderr.strip())
    return result


def quote(value):
    require(not any(c in value for c in '\n\r\0'), 'unsupported systemd executable path')
    return '"' + value.replace('\\','\\\\').replace('"','\\"').replace('%','%%') + '"'


def units(paths, interpreter):
    # The user manager need not share the installing shell's XDG variables; bind the
    # roots this installation uses so scheduled syncs find the same control state.
    roots = {'XDG_STATE_HOME': str(paths.state.parent), 'XDG_DATA_HOME': str(paths.data.parent)}
    service = ('[Unit]\nDescription=Receive validated agents source\n'
        '[Service]\nType=oneshot\nUMask=0077\n' +
        ''.join('Environment=' + quote(name + '=' + value) + '\n' for name, value in roots.items()) +
        'ExecStart=' + quote(interpreter) +
        ' -I ' + quote(str(paths.launcher)) + ' sync\n')
    timer = ('[Unit]\nDescription=Check agents source every five minutes\n'
        '[Timer]\nOnStartupSec=30s\nOnCalendar=*:0/5\nPersistent=true\nUnit=agents-receive.service\n'
        '[Install]\nWantedBy=timers.target\n')
    return {'agents-receive.service':service.encode(), 'agents-receive.timer':timer.encode()}


def receive(paths, action):
    with source_lock(paths):
        file = paths.control/'profile.json'
        config = load(file)
        require(action in ('enable','disable'), 'unknown receive action')
        require(action != 'enable' or config['profile'] == 'receiver', 'author profile cannot enable automatic receiving')
        receipt_file = paths.control/'service-units.json'
        receipt = load(receipt_file) if receipt_file.exists() else {'schema_version':1,'files':[]}
        if action == 'disable' and not receipt['files']:
            config['receive_enabled'] = False
            write_json(file,config)
            return {'receive_enabled':False,'automatic_receive':'not installed','manual_sync':'agents sync'}
        require(sys.platform.startswith('linux'), 'automatic receiving requires a usable Linux systemd user manager; manual sync remains available')
        systemctl('show-environment')
        if action == 'disable':
            systemctl('disable','--now','agents-receive.timer')
            config['receive_enabled'] = False
            write_json(file,config)
            return {'receive_enabled':False,'manual_sync':'agents sync'}
        installed = load(paths.control/'bootstrap-active.json')
        interpreter = load(no_links(installed['installation'])/'installation.json')['interpreter']
        require(interpreter.startswith('/'), 'service needs an absolute interpreter')
        candidate = units(paths,interpreter)
        folder = no_links(paths.home/'.config/systemd/user')
        owned = {row['name']:row['sha256'] for row in receipt['files']}
        for name in candidate:
            target = no_links(folder/name)
            if target.exists():
                require(name in owned and digest(read(target)) == owned[name], 'unowned or modified systemd unit; preserve it: ' + name)
        # Receipt precedes daemon activation so failed enable remains recoverable.
        for name,data in candidate.items():
            atomic(folder/name,data,0o644)
        write_json(receipt_file,{'schema_version':1,'files':[
            {'name':name,'sha256':digest(data)} for name,data in sorted(candidate.items())]})
        systemctl('daemon-reload')
        systemctl('enable','--now','agents-receive.timer')
        config['receive_enabled'] = True
        write_json(file,config)
        return {'receive_enabled':True,'timer':'agents-receive.timer','manual_sync':'agents sync',
                'interpreter':interpreter,'launcher':str(paths.launcher)}
