"""为现有 Caddy 增加独立静态站点；保存原入口并限定只重建 edge。"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

BASE = Path('/opt/sigou-notes')
GATEWAY = Path('/opt/llm_gateway')
CADDY = GATEWAY / 'deploy/lite/Caddyfile'
MANAGE = GATEWAY / 'manage.sh'
EDGE = 'llm-gateway-lite-edge-1'
IMPORT = 'import /etc/caddy/sigou-notes.caddy'
OVERRIDE = BASE / 'deploy/compose.sigou-notes.yaml'


def run(*args):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): {result.stderr[-1800:]}')
    return result.stdout.strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def containers():
    output = run('docker', 'ps', '--filter', 'label=com.docker.compose.project=llm-gateway-lite',
                 '--format', '{{.Names}} {{.ID}}')
    return dict(line.split() for line in output.splitlines())


def compose(*extra):
    # 完整配置只在进程内比较，避免环境文件中的凭据进入日志或发布证据。
    return json.loads(run(MANAGE, *extra, 'config', '--format', 'json'))


def check_services(before, after):
    if before.keys() != after.keys():
        raise RuntimeError('Compose service set changed')
    for name in before:
        old, new = dict(before[name]), dict(after[name])
        if name == 'edge':
            old_mounts = {item['target']: item for item in old.pop('volumes', [])}
            new_mounts = {item['target']: item for item in new.pop('volumes', [])}
            additions = {'/srv/sigou-notes': (BASE / 'site').as_posix(),
                         '/etc/caddy/sigou-notes.caddy': (BASE / 'deploy/site.caddy').as_posix()}
            if new_mounts.keys() != old_mounts.keys() | additions.keys():
                raise RuntimeError('Unexpected edge mount set')
            for target, mount in old_mounts.items():
                if new_mounts[target] != mount:
                    raise RuntimeError(f'Existing edge mount changed: {target}')
            for target, source in additions.items():
                mount = new_mounts[target]
                if mount.get('source') != source or mount.get('type') != 'bind' or mount.get('read_only') is not True:
                    raise RuntimeError(f'Invalid site mount: {target}')
        if old != new:
            raise RuntimeError(f'Unexpected service configuration change: {name}')


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    path.chmod(0o600)


def prepare(release, expected_hash):
    archive = release / 'site.zip'
    if digest(archive) != expected_hash:
        raise RuntimeError('Release archive checksum mismatch')
    backup = release / 'backup'
    if backup.exists():
        raise RuntimeError('Backup already exists; inspect the previous preparation first')
    if (BASE / 'active.json').exists() or (BASE / 'site/public').exists():
        raise RuntimeError('Initial installation only; preserve the existing site')
    backup.mkdir(mode=0o700)
    for source, name in ((CADDY, 'Caddyfile'), (MANAGE, 'manage.sh')):
        shutil.copy2(source, backup / name)

    source = release / 'source'
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            name = PurePosixPath(entry.filename)
            if name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0] not in ('public', 'deploy'):
                raise RuntimeError('Unexpected archive path')
        package.extractall(source)

    original = CADDY.read_text(encoding='utf-8')
    management = MANAGE.read_text(encoding='utf-8')
    if IMPORT in original or management.count('"$@"') != 1 or str(OVERRIDE) in management:
        raise RuntimeError('Entry configuration does not match the expected initial state')
    (release / 'candidate.Caddyfile').write_text(original.rstrip() + '\n\n' + IMPORT + '\n', encoding='utf-8')
    (release / 'candidate.manage.sh').write_text(
        management.replace('"$@"', f'-f {OVERRIDE} "$@"'), encoding='utf-8')

    before = compose()
    candidate = compose('-f', source / 'deploy/compose.sigou-notes.yaml')
    check_services(before['services'], candidate['services'])
    configuration = json.loads(run('docker', 'inspect', EDGE))[0]['Config']
    domain_env = [value for value in configuration['Env']
                  if value.startswith(('GW_API_HOST=', 'GW_CONSOLE_HOST='))]
    command = ['docker', 'run', '--rm', '--network', 'none']
    for value in domain_env:
        command.extend(['-e', value])
    command.extend([
        '-v', f'{release}/candidate.Caddyfile:/etc/caddy/Caddyfile:ro',
        '-v', f'{source}/deploy/site.caddy:/etc/caddy/sigou-notes.caddy:ro',
        '-v', f'{source}/public:/srv/sigou-notes/public:ro',
        configuration['Image'], 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile'])
    run(*command)
    report = {'release': release.name, 'archive_sha256': expected_hash, 'state': 'prepared',
              'caddy_before_sha256': digest(CADDY), 'manage_before_sha256': digest(MANAGE),
              'containers_before': containers(), 'caddy_validation': 'passed',
              'non_edge_config_comparison': 'identical'}
    save_json(release / 'report.json', report)
    print(json.dumps(report, ensure_ascii=False))


def restore_entry(release):
    for target, name in ((CADDY, 'Caddyfile'), (MANAGE, 'manage.sh')):
        shutil.copy2(release / 'backup' / name, target)
    run(MANAGE, '--profile', 'public', 'up', '--no-deps', '--no-build', '-d', 'edge')
    if (BASE / 'active.json').exists():
        save_json(BASE / 'active.json', {'release': release.name, 'state': 'entry_restored'})


def activate(release):
    report = json.loads((release / 'report.json').read_text(encoding='utf-8'))
    if report['state'] != 'prepared':
        raise RuntimeError('Release is not in prepared state')
    if digest(CADDY) != report['caddy_before_sha256'] or digest(MANAGE) != report['manage_before_sha256']:
        raise RuntimeError('Server entry changed after preparation')
    original = compose()
    (BASE / 'deploy').mkdir(exist_ok=True)
    (BASE / 'site').mkdir(exist_ok=True)
    shutil.copytree(release / 'source/public', BASE / 'site/public')
    for name in ('site.caddy', 'compose.sigou-notes.yaml'):
        shutil.copy2(release / 'source/deploy' / name, BASE / 'deploy' / name)
    try:
        shutil.copyfile(release / 'candidate.Caddyfile', CADDY)
        shutil.copyfile(release / 'candidate.manage.sh', MANAGE)
        MANAGE.chmod(0o755)
        check_services(original['services'], compose()['services'])
        run(MANAGE, '--profile', 'public', 'up', '--no-deps', '--no-build', '-d', 'edge')
        after = containers()
        for name, identifier in report['containers_before'].items():
            if name != EDGE and after.get(name) != identifier:
                raise RuntimeError(f'Unexpected container change: {name}')
        run('curl', '--fail', '--silent', '--show-error', '--max-time', '20',
            'https://console.linhengyi.xyz/', '-o', '/dev/null')
        api_status = run('curl', '--silent', '--show-error', '--max-time', '20', '-o', '/dev/null',
                         '-w', '%{http_code}', 'https://api.linhengyi.xyz/v1/models')
        if api_status != '401':
            raise RuntimeError(f'Unexpected unauthenticated API status: {api_status}')
        report.update(state='activated', containers_after=after, console_status=200,
                      unauthenticated_api_status=401, non_edge_containers='unchanged')
        save_json(release / 'report.json', report)
        save_json(BASE / 'active.json', {'release': release.name, 'public_root': str(BASE / 'site/public')})
    except Exception:
        restore_entry(release)
        report['state'] = 'entry_restored_after_activation_failure'
        save_json(release / 'report.json', report)
        raise
    print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'activate', 'rollback'))
    parser.add_argument('--release', required=True)
    parser.add_argument('--sha256')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,70}', args.release):
        parser.error('Invalid release name')
    release = BASE / 'releases' / args.release
    if args.action == 'prepare':
        if not args.sha256 or not re.fullmatch(r'[0-9a-f]{64}', args.sha256):
            parser.error('A SHA256 checksum is required')
        prepare(release, args.sha256)
    elif args.action == 'activate':
        activate(release)
    else:
        restore_entry(release)
        print('Original Caddy and management entry restored; site files retained')


if __name__ == '__main__':
    main()
