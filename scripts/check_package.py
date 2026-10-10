"""Check skill resources; this does not validate presentation content or rendering."""
from pathlib import Path
import argparse
import re
import shutil
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET

REQUIRED = (
    'SKILL.md', 'README.md', 'LICENSE', 'agents/openai.yaml',
    'references/content-and-evidence.md', 'references/visual-design.md',
    'references/quality-and-delivery.md', 'references/sources.md',
    'assets/gallery/index.md', 'assets/gallery/research-framework.svg',
    'assets/gallery/evidence-workflow.svg', 'assets/gallery/revision-comparison.svg',
)

def check(root):
    root = root.resolve()
    errors = []
    for rel in REQUIRED:
        if not (root / rel).is_file(): errors.append(f'Missing required resource: {rel}')
    for file in sorted(root.rglob('*')):
        if not file.is_file() or '.git' in file.parts or '__pycache__' in file.parts: continue
        rel = file.relative_to(root).as_posix()
        if file.name == '.env' or file.name.startswith('.env.'):
            errors.append(f'Private environment file in package: {rel}')
        if file.suffix.lower() not in ('.md', '.yaml', '.svg'): continue
        raw = file.read_text(encoding='utf-8')
        if re.search(r'(?i)[A-Z]:[/\\](?:Users|Documents)[/\\]|/home/[^/\s]+/', raw):
            errors.append(f'Personal absolute path in publishable file: {rel}')
        if file.suffix == '.md':
            for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', raw):
                target = target.strip().strip('<>')
                url = urllib.parse.urlsplit(target)
                if url.scheme or target.startswith('#'): continue
                destination = (file.parent / urllib.parse.unquote(url.path)).resolve()
                if not destination.is_relative_to(root):
                    errors.append(f'Link escapes package: {rel} -> {target}')
                elif not destination.exists():
                    errors.append(f'Broken local link: {rel} -> {target}')
        if file.suffix == '.svg':
            try:
                svg = ET.fromstring(raw)
                if svg.tag != '{http://www.w3.org/2000/svg}svg':
                    errors.append(f'Invalid SVG root: {rel}')
                if svg.attrib.get('viewBox') != '0 0 1600 900':
                    errors.append(f'Unexpected sample canvas: {rel}')
                if '教学布局示例' not in raw or '非实验结果' not in raw:
                    errors.append(f'Missing sample disclosure: {rel}')
                ids = {el.attrib['id'] for el in svg.iter() if 'id' in el.attrib}
                for el in svg.iter():
                    tag = el.tag.rsplit('}', 1)[-1]
                    if tag in ('script', 'foreignObject', 'image', 'use'):
                        errors.append(f'Unsupported or external SVG element {tag}: {rel}')
                    for attr, value in el.attrib.items():
                        name = attr.rsplit('}', 1)[-1].lower()
                        if name.startswith('on') or name == 'href':
                            errors.append(f'Active or linked SVG attribute: {rel}')
                        for reference in re.findall(r'url\(([^)]+)\)', value):
                            if not reference.startswith('#') or reference[1:] not in ids:
                                errors.append(f'Unresolved SVG reference: {rel} -> {reference}')
                    if tag == 'text':
                        x, y = float(el.attrib.get('x', 0)), float(el.attrib.get('y', 0))
                        if not (0 <= x <= 1600 and 0 <= y <= 900):
                            errors.append(f'Text origin outside canvas: {rel}')
            except (ET.ParseError, ValueError) as exc:
                errors.append(f'Invalid SVG: {rel}: {exc}')
    return errors

def self_test(root):
    # Independent failures verify that checks catch broken packages.
    with tempfile.TemporaryDirectory(prefix='academic-ppt-check-') as temp:
        sandbox = Path(temp)/'skill'
        shutil.copytree(root, sandbox, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        assert not check(sandbox), 'Baseline package failed'
        sample = sandbox/'assets/gallery/research-framework.svg'
        original = sample.read_text(encoding='utf-8')
        sample.unlink()
        assert any('Missing required' in e and 'research-framework.svg' in e for e in check(sandbox))
        assert any('Broken local link' in e for e in check(sandbox))
        sample.write_text(original, encoding='utf-8')
        sample.write_text(original.replace('</svg>', '<image href="https://example.invalid/a.png"/></svg>'), encoding='utf-8')
        assert any('SVG element image' in e for e in check(sandbox))
        sample.write_text(original.replace('</svg>', '<script>alert(1)</script></svg>'), encoding='utf-8')
        assert any('SVG element script' in e for e in check(sandbox))
        sample.write_text(original, encoding='utf-8')
        private = sandbox/'private-note.md'
        private.write_text('C:/Users/example/private.txt', encoding='utf-8')
        assert any('Personal absolute path' in e for e in check(sandbox))
        private.write_text('[outside](../../../outside.md)', encoding='utf-8')
        assert any('Link escapes package' in e for e in check(sandbox))
        private.unlink()
        assert not check(sandbox), 'Restored package failed'
    return 5

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    errors = check(args.root)
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'Package checks passed: {len(REQUIRED)} required resources; local links and SVG references valid.')
    if args.self_test:
        print(f'Self-test passed: {self_test(args.root)} negative cases and restored baseline.')
    print('Scope: package integrity only; no PPT or scientific accuracy claim.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
