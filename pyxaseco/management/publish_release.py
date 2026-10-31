"""Build one signed release for publication on GitHub and tmtrialgy.com."""

import argparse
import base64
from datetime import datetime, timedelta, timezone
import getpass
import io
import json
import re
from pathlib import Path
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .config_store import ManagementError, revision
from .installation import safe_path, _write
from .release_manifest import (
    FILE_LIMIT, METADATA_LIMIT, SIGNING_CONTEXT, GITHUB_HOSTS, WEBSITE_HOSTS,
    package_path, https_url, validate_archive, verify_catalogue, version,
)


def public_key(key):
    return base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def inventory(root, package):
    root = safe_path(root)
    files = {}
    # Only distributable paths accepted by the controller, never secrets or runtime data.
    start = root / 'apps' / package['id'] if package['kind'] == 'app' else root
    if not start.is_dir():
        return files
    import os
    for directory, dirs, names in os.walk(start, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in {
            '__pycache__', '00removed', '__disabled__', 'ToPort', 'Validation', 'envrotator',
        } and not name.startswith('.') and not (Path(directory) / name).is_symlink()
            and not (Path(directory) / name).is_junction())
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            try:
                package_path(relative, package)
            except ManagementError:
                continue
            safe_path(path)
            if path.stat().st_size > FILE_LIMIT:
                raise ManagementError('Oversized distribution file: ' + relative)
            files[relative] = path.read_bytes()
    return dict(sorted(files.items()))


def build(source, baseline, output, key, *, identity, release, baseline_version,
          channel, github_base, site_base, days=30, libraries=()):
    version(release)
    version(baseline_version)
    if channel not in {'stable', 'development'} or not 1 <= days <= 90:
        raise ManagementError('Choose a supported channel and 1-90 days of approval')
    github_base = https_url(github_base.rstrip('/'), GITHUB_HOSTS)
    site_base = https_url(site_base.rstrip('/'), WEBSITE_HOSTS)
    package = {'id': identity, 'kind': 'controller' if identity == 'controller' else 'app'}
    from .release_manifest import PUBLIC_APPS
    if identity != 'controller' and identity not in PUBLIC_APPS:
        raise ManagementError('Unknown public package ID')
    files, previous = inventory(source, package), inventory(baseline, package)
    requirements = {}
    lines = files.get('requirements.txt', b'').decode('utf-8-sig').splitlines() + list(libraries)
    for line in lines:
        line = line.partition('#')[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]{0,99})==([0-9][A-Za-z0-9.!+_-]{0,79})', line)
        if not match:
            raise ManagementError('Use exact name==version library requirements in a release')
        name, pinned = match.groups()
        normalized = re.sub('[-_.]+', '-', name).lower()
        item = {'name': name, 'version': pinned}
        if normalized in requirements and requirements[normalized] != item:
            raise ManagementError('Conflicting library declarations: ' + name)
        requirements[normalized] = item
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    blob = buffer.getvalue()
    hashes = lambda entries: {name: {'sha256': revision(data), 'size': len(data)} for name, data in entries.items()}
    filename = identity + '-' + release + '.zip'
    package.update(version=release, sha256=revision(blob), size=len(blob), files=hashes(files),
        baseline={'version': baseline_version, 'files': hashes(previous)},
        urls=[github_base + '/' + filename,
              site_base + '/api/pyxaseco/updates/files/' + channel + '/' + release + '/' + filename],
        python={'min': '3.12', 'max_exclusive': '4.0'},
        controller={'min': '1.4', 'max_exclusive': '2.0'}, requires_apps={},
        python_requirements=list(requirements.values()))
    validate_archive(blob, package)
    output = safe_path(output)
    output.mkdir(parents=True, exist_ok=True)
    public = public_key(key)
    public_path = safe_path(output / 'public-key.txt')
    if public_path.exists() and public_path.read_text().strip() != public:
        raise ManagementError('Publication folder already uses a different signing key')
    catalogue_path = safe_path(output / channel / 'catalogue.json')
    sequence, packages = 1, []
    if catalogue_path.exists():
        if catalogue_path.stat().st_size > METADATA_LIMIT:
            raise ManagementError('Existing catalogue is oversized')
        # The owner can renew an expired catalogue, but cannot accept an invalid signature.
        old, _digest = verify_catalogue(catalogue_path.read_bytes(), public, channel,
                                       now=datetime.min.replace(tzinfo=timezone.utc))
        sequence, packages = old['sequence'] + 1, old['packages']
    packages = [item for item in packages if item['id'] != identity] + [package]
    catalogue = {'schema': 1, 'sequence': sequence, 'channel': channel,
                 'expires': (datetime.now(timezone.utc) + timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                 'packages': sorted(packages, key=lambda p: p['id'])}
    signed = json.dumps(catalogue, sort_keys=True, separators=(',', ':')).encode()
    envelope = (json.dumps({'signed': base64.b64encode(signed).decode(),
        'signature': base64.b64encode(key.sign(SIGNING_CONTEXT + signed)).decode()}, indent=2) + '\n').encode()
    verify_catalogue(envelope, public, channel)
    target = safe_path(output / channel / release / filename)
    from .maintenance import _bytes, _replace
    existing = target.read_bytes() if target.exists() else None
    if existing is not None and existing != blob:
        raise ManagementError('Published ZIPs are immutable; choose a new version for changed files')
    if existing is None:
        _write(target, blob)
    if not public_path.exists():
        _write(public_path, (public + '\n').encode())
    before = _bytes(catalogue_path)
    _replace(catalogue_path, envelope, revision(before) if before is not None else None)
    return {'catalogue': str(catalogue_path), 'zip': str(target), 'public_key': public,
            'sequence': sequence, 'files': len(files), 'baseline_files': len(previous)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    create = commands.add_parser('keygen', help='Create an encrypted private signing key outside publishing folders')
    create.add_argument('--key', required=True)
    pack = commands.add_parser('build')
    for name in ('source', 'baseline', 'baseline-version', 'version', 'key', 'output', 'github-base'):
        pack.add_argument('--' + name, required=True)
    pack.add_argument('--site-base', default='https://tmtrialgy.com')
    pack.add_argument('--package', default='controller')
    pack.add_argument('--channel', choices=('stable', 'development'), default='development')
    pack.add_argument('--library', action='append', default=[], help='Required existing library, name==version; repeat for optional apps')
    args = parser.parse_args(argv)
    try:
        key_path = safe_path(args.key)
        if args.action == 'keygen':
            password = getpass.getpass('Signing-key passphrase: ')
            if len(password) < 12 or password != getpass.getpass('Repeat passphrase: '):
                raise ManagementError('Use a matching passphrase of at least 12 characters')
            key = Ed25519PrivateKey.generate()
            _write(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                    serialization.BestAvailableEncryption(password.encode())), private=True)
            print('Trusted public key: ' + public_key(key))
            return 0
        output = safe_path(args.output)
        if key_path == output or output in key_path.parents or safe_path(args.source) in key_path.parents:
            raise ManagementError('Keep the private key outside the source and publication folders')
        key = serialization.load_pem_private_key(key_path.read_bytes(),
                password=getpass.getpass('Signing-key passphrase: ').encode())
        if not isinstance(key, Ed25519PrivateKey):
            raise ManagementError('The publisher needs an Ed25519 private key')
        result = build(args.source, args.baseline, output, key, identity=args.package, release=args.version,
            baseline_version=args.baseline_version, channel=args.channel,
            github_base=args.github_base, site_base=args.site_base, libraries=args.library)
        print(json.dumps(result, indent=2))
        return 0
    except (ManagementError, OSError, ValueError) as error:
        print(str(error) if isinstance(error, ManagementError) else 'Could not read the signing key or release files')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
