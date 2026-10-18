"""Package tracked source and one Windows EXE; never include local user state."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--out', type=Path, default=Path('build/release'))
    args = parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', args.version):
        parser.error('Expected a semantic version, e.g. 1.0.0')
    root = Path(__file__).resolve().parents[1]
    exe = args.exe.resolve()
    if not exe.is_file() or exe.read_bytes()[:2] != b'MZ':
        parser.error('Expected an existing Windows EXE')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    standalone = out / 'YandexMusicPresence.exe'
    if exe != standalone:
        shutil.copyfile(exe, standalone)
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0')
    files = []
    for name in filter(None, names):
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Tracked path is missing or outside repository: ' + name)
        files.append((name, path))
    if not any(name == 'LICENSE' for name, _ in files):
        raise ValueError('Stage or commit the source before packaging')
    archive = out / f'YandexMusicPresence-{args.version}-windows-x64.zip'
    prefix = 'YandexMusicPresence/'
    inner_checksums = []
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for name, path in sorted(files) + [('YandexMusicPresence.exe', standalone)]:
            package.write(path, prefix + name)
            inner_checksums.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + name)
        package.writestr(prefix + 'SHA256SUMS.txt', '\n'.join(inner_checksums) + '\n')
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None:
            raise ValueError('ZIP integrity check failed')
    checksums = out / 'SHA256SUMS.txt'
    checksums.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                                 for p in (standalone, archive)), encoding='utf-8')
    print(f'Packaged {len(files)} source/assets files + EXE: {archive}')
    print(f'Checksums: {checksums}')


if __name__ == '__main__':
    main()
