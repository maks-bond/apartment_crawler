#!/usr/bin/env python3
"""Run on the browser computer: add a backed-up, on-demand SSH dashboard alias."""
import argparse
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path


def settings(text):
    result = {}
    for line in text.splitlines():
        key,separator,value = line.partition(' ')
        if separator:
            result.setdefault(key.lower(),[]).append(value)
    return result


def quoted(value):
    if '\n' in value or '\r' in value:
        raise ValueError('Multiline SSH option is unsupported')
    return '"'+value.replace('\\','\\\\').replace('"','\\"')+'"'


def block(alias, effective, project, local_port, remote_port):
    lines = [f'# BEGIN {alias} — managed apartment dashboard',f'Host {alias}']
    for key in ['hostname','user','port','identityfile','certificatefile','identityagent',
                'identitiesonly','proxyjump','proxycommand','hostkeyalias','preferredauthentications']:
        for value in effective.get(key,[]):
            if value.lower()!='none':
                lines.append(f'    {key} '+(value if key=='proxycommand' else quoted(value)))
    command = f'cd {shlex.quote(str(project))} && exec sh scripts/dashboard.sh --port {remote_port}'
    lines.extend(['    ExitOnForwardFailure yes','    ServerAliveInterval 30','    ServerAliveCountMax 3',
                  '    RequestTTY force',f'    LocalForward 127.0.0.1:{local_port} 127.0.0.1:{remote_port}',
                  '    RemoteCommand '+command.replace('%','%%'),
                  'Host *',f'# END {alias} — managed apartment dashboard',''])
    return '\n'.join(lines)+'\n'


def update_config(original, alias, addition):
    pattern = r'(?ms)^# BEGIN '+re.escape(alias)+r' — managed apartment dashboard\n.*?^# END '+re.escape(alias)+r' — managed apartment dashboard\n\n?'
    clean = re.sub(pattern,'',original)
    for match in re.finditer(r'(?mi)^\s*Host\s+([^\n]+)',clean):
        if alias in shlex.split(match[1],comments=True):
            raise ValueError(f'An unmanaged Host {alias} entry already exists; choose --alias')
    # Specific options must precede wildcard defaults. Host * restores global context
    # for any original directives before the first Host/Match declaration.
    return addition+clean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ssh_target',help='The host or alias you already use to SSH to the collector machine')
    parser.add_argument('--alias',default='apartment-dashboard')
    parser.add_argument('--config',type=Path,default=Path.home()/'.ssh/config')
    parser.add_argument('--project',type=Path,default=Path('/home/maksym/dev/apartment_crawler'))
    parser.add_argument('--local-port',type=int,default=8765)
    parser.add_argument('--remote-port',type=int,default=8765)
    parser.add_argument('--dry-run',action='store_true',help='Print the proposed block without changing files')
    args = parser.parse_args()
    if not re.fullmatch(r'[\w.-]+',args.alias) or args.ssh_target.startswith('-'):
        parser.error('Invalid alias or SSH target')
    if not (1<=args.local_port<=65535 and 1<=args.remote_port<=65535):
        parser.error('Ports must be between 1 and 65535')
    if not args.project.is_absolute() or '\n' in str(args.project):
        parser.error('Remote project path must be absolute')
    command = ['ssh','-G']
    if args.config.exists():
        command.extend(['-F',str(args.config)])
    effective = settings(subprocess.run(command+[args.ssh_target],capture_output=True,text=True,check=True).stdout)
    if not effective.get('hostname') or not effective.get('user'):
        parser.error('Could not resolve the existing SSH connection')
    addition = block(args.alias,effective,args.project,args.local_port,args.remote_port)
    original = args.config.read_text() if args.config.exists() else ''
    updated = update_config(original,args.alias,addition)
    if args.dry_run:
        print(addition)
        return
    args.config.parent.mkdir(parents=True,exist_ok=True)
    if args.config.exists():
        backup = args.config.with_name(args.config.name+'.backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.write_text(original)
        backup.chmod(0o600)
        print(f'Backup: {backup}')
    temporary = args.config.with_name(args.config.name+'.dashboard-tmp')
    temporary.write_text(updated)
    temporary.chmod(0o600)
    temporary.replace(args.config)
    print(f'Configured: ssh {args.alias}')
    print(f'Browser: http://127.0.0.1:{args.local_port} — Ctrl+C stops the dashboard and tunnel')


if __name__=='__main__':
    main()
