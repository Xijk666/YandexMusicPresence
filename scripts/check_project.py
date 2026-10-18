"""Check source syntax, bilingual documentation links and SVG assets offline."""
import ast
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def main():
    root = Path(__file__).resolve().parents[1]
    errors = []
    version = (root / 'VERSION').read_text('utf-8').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', version):
        errors.append('Invalid VERSION')
    for folder in ('src', 'tests', 'scripts'):
        for path in (root / folder).glob('*.py'):
            try:
                ast.parse(path.read_text('utf-8'), filename=str(path))
            except SyntaxError as exc:
                errors.append(str(exc))
    documents = [root / name for name in ('README.md', 'README.ru.md', 'CONTRIBUTING.md',
                                          'SECURITY.md', 'CHANGELOG.md', 'THIRD_PARTY_NOTICES.md')]
    documents += list((root / 'docs').glob('*.md'))
    for path in documents:
        text = path.read_text('utf-8')
        links = re.findall(r'\]\(([^)]+)\)', text) + re.findall(r'(?:src|href)="([^"]+)"', text)
        for link in links:
            if '://' in link or link.startswith(('#', 'mailto:')):
                continue
            target = (path.parent / link.split('#')[0]).resolve()
            if not target.is_relative_to(root) or not target.exists():
                errors.append(f'{path.name}: missing local link {link}')
        if re.search(r'C:[/\\]Users[/\\]', text, re.IGNORECASE):
            errors.append(f'{path.name}: personal absolute Windows path')
    for name in ('README.md', 'README.ru.md'):
        text = (root / name).read_text('utf-8')
        if 'README.ru.md' not in text or 'README.md' not in text:
            errors.append(f'{name}: language switch is missing')
    for path in (root / 'docs' / 'assets').glob('*.svg'):
        tree = ET.parse(path)
        for item in tree.iter():
            if item.tag.rsplit('}', 1)[-1] in ('script', 'foreignObject'):
                errors.append(f'{path.name}: unsupported active SVG element')
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Project checks passed: v{version}, syntax, {len(documents)} documents, local links and SVGs.')


if __name__ == '__main__':
    main()
