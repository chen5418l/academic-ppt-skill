"""Check skill resources; this does not validate presentation content or rendering."""
from pathlib import Path
import argparse
import io
import json
import posixpath
import re
import shutil
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
import struct

REQUIRED = (
    'SKILL.md', 'README.md', 'LICENSE', 'agents/openai.yaml',
    'references/content-and-evidence.md', 'references/visual-design.md',
    'references/quality-and-delivery.md', 'references/sources.md',
    'assets/gallery/index.md', 'assets/gallery/research-framework.svg',
    'assets/gallery/evidence-workflow.svg', 'assets/gallery/revision-comparison.svg',
    'assets/preferences/default.json', 'references/preferences-and-density.md',
    'references/behavioral-cases.md', 'examples/transformer/index.md',
    'assets/templates/academic-layouts-v2.0.pptx',
    'examples/transformer/transformer-reading-example-v2.pptx',
    'references/reference-adaptation.md', 'references/evidence-and-revisions.md',
    'scripts/audit_deck.py', 'scripts/test_audit_deck.py',
    'examples/deepopf/index.md', 'examples/deepopf/evidence.json',
    'examples/deepopf/deepopf-academic-v3.pptx',
    'examples/deepopf/figures/notes.md',
    'examples/deepopf/figures/architecture.png',
    'examples/deepopf/figures/reconstruction.png',
    'examples/deepopf/figures/data-route.png',
    'examples/deepopf/figures/research-extension.png',
)
NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
      'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
SAMPLES = {
    'assets/templates/academic-layouts-v2.0.pptx': (8, {4, 5}, 6, [12, 16, 19]),
    'examples/transformer/transformer-reading-example-v2.pptx': (6, {4}, 5, [25.16, 27.3, 28.4]),
}

def check_pptx(file, spec):
    errors = []
    count, table_pages, chart_page, expected_values = spec
    try:
        with zipfile.ZipFile(file) as z:
            bad = z.testzip()
            if bad: errors.append(f'Corrupt ZIP member: {bad}')
            names = set(z.namelist())
            for name in names:
                if name.endswith(('.xml', '.rels')): ET.fromstring(z.read(name))
            slides = {n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)}
            if len(slides) != count: errors.append(f'Unexpected slide count: {len(slides)} != {count}')
            for page in range(1, count + 1):
                name = f'ppt/slides/slide{page}.xml'
                if name not in names: continue
                slide = ET.fromstring(z.read(name))
                if not slide.findall('.//p:sp', NS): errors.append(f'No native shapes on slide {page}')
                if page in table_pages and not slide.findall('.//a:tbl', NS):
                    errors.append(f'No native table on slide {page}')
                if page == chart_page and not slide.findall('.//c:chart', NS):
                    errors.append(f'No native chart on slide {page}')
                rel_name = f'ppt/slides/_rels/slide{page}.xml.rels'
                rels = ET.fromstring(z.read(rel_name))
                notes = [r for r in rels if r.attrib.get('Type', '').endswith('/notesSlide')]
                if len(notes) != 1:
                    errors.append(f'Missing notes on slide {page}')
                else:
                    target = notes[0].attrib['Target']
                    dest = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('ppt/slides', target))
                    raw = ET.fromstring(z.read(dest))
                    body = ''.join(t.text or '' for t in raw.findall('.//a:t', NS)).strip()
                    if len(body) < 8: errors.append(f'Empty notes on slide {page}')
            for name in names:
                if not name.endswith('.rels'): continue
                source_dir = posixpath.dirname(posixpath.dirname(name))
                for r in ET.fromstring(z.read(name)):
                    target = r.attrib.get('Target', '')
                    if r.attrib.get('TargetMode') == 'External':
                        errors.append(f'External relationship in {name}')
                    else:
                        dest = posixpath.normpath(posixpath.join(source_dir, target.lstrip('/'))) if not target.startswith('/') else target.lstrip('/')
                        if dest not in names: errors.append(f'Broken PPT relationship: {name} -> {target}')
            charts = [n for n in names if n.endswith('.xml') and '/charts/' in n and '/_rels/' not in n]
            if len(charts) != 1: errors.append(f'Unexpected chart count: {len(charts)}')
            else:
                chart = ET.fromstring(z.read(charts[0]))
                values = [float(v.text) for v in chart.findall('.//c:val/c:numRef/c:numCache/c:pt/c:v', NS)]
                if not values:
                    values = [float(v.text) for v in chart.findall('.//c:val/c:numLit/c:pt/c:v', NS)]
                if values != expected_values: errors.append(f'Unexpected chart values: {values}')
            if not any(n.startswith('ppt/embeddings/') and n.endswith('.xlsx') for n in names):
                errors.append('Missing embedded chart workbook')
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError, ValueError) as exc:
        errors.append(f'Invalid PPTX: {exc}')
    return errors

def check(root):
    root = root.resolve()
    errors = []
    for rel in REQUIRED:
        if not (root / rel).is_file(): errors.append(f'Missing required resource: {rel}')
    for file in sorted(root.rglob('*')):
        if not file.is_file() or '.git' in file.parts or '__pycache__' in file.parts: continue
        rel = file.relative_to(root).as_posix()
        if file.name == '.env' or file.name.startswith('.env.') or file.name.endswith('.local.json') or 'gallery-local' in file.relative_to(root).parts:
            errors.append(f'Private environment file in package: {rel}')
        if file.suffix.lower() not in ('.md', '.yaml', '.svg', '.json', '.py'): continue
        raw = file.read_text(encoding='utf-8')
        if re.search(r'(?i)[A-Z]:[/\\](?:Users|Documents)[/\\]|' + '/' + r'home/[^/\s]+/', raw):
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
    profile = root/'assets/preferences/default.json'
    if profile.is_file():
        try:
            obj = json.loads(profile.read_text(encoding='utf-8'))
            if obj.get('schema_version') != 1 or obj.get('density') not in ('talk', 'standalone'):
                errors.append('Invalid default preference format or density')
            if obj.get('aspect_ratio') not in ('16:9', '4:3'): errors.append('Invalid default aspect ratio')
            if any(not isinstance(obj.get(k), bool) for k in ('editable_diagrams', 'speaker_notes')):
                errors.append('Invalid preference boolean')
            if not all(re.fullmatch(r'#[0-9a-fA-F]{6}', obj.get('palette', {}).get(k, '')) for k in ('core', 'inputs', 'evidence')):
                errors.append('Invalid palette')
        except (ValueError, AttributeError, TypeError) as exc:
            errors.append(f'Invalid default preferences: {exc}')
    for rel, spec in SAMPLES.items():
        file = root/rel
        if not file.is_file(): continue
        errors.extend(f'{rel}: {e}' for e in check_pptx(file, spec))
        previews = file.parent/'previews'
        expected = {f'slide-{n:02d}.png' for n in range(1, spec[0]+1)}
        found = {f.name for f in previews.glob('*.png')}
        if found != expected: errors.append(f'Unexpected preview set: {rel}')
        for file in previews.glob('*.png'):
            data = file.read_bytes()
            if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', data[16:24]) != (1600, 900):
                errors.append(f'Invalid preview PNG: {file.relative_to(root)}')
    case = root/'examples/deepopf'
    deck = case/'deepopf-academic-v3.pptx'
    evidence = case/'evidence.json'
    if deck.is_file() and evidence.is_file():
        try:
            from audit_deck import check as audit
            data = json.loads(evidence.read_text(encoding='utf-8'))
            errors.extend('DeepOPF: '+e for e in audit(deck, data))
            expected = {f'slide-{n:02d}.png' for n in range(1,21)}
            if {f.name for f in (case/'previews').glob('*.png')} != expected:
                errors.append('Unexpected DeepOPF preview set')
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
            errors.append('Invalid DeepOPF case: '+str(exc))
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
        private.write_text('C:' + '/Users/example/private.txt', encoding='utf-8')
        assert any('Personal absolute path' in e for e in check(sandbox))
        private.write_text('[outside](../../../outside.md)', encoding='utf-8')
        assert any('Link escapes package' in e for e in check(sandbox))
        private.unlink()
        deck = sandbox/'assets/templates/academic-layouts-v2.0.pptx'
        original_deck = deck.read_bytes()
        deck.write_bytes(b'not-a-zip')
        assert any('Invalid PPTX' in e for e in check(sandbox))
        deck.write_bytes(original_deck)
        with zipfile.ZipFile(io.BytesIO(original_deck)) as z:
            entries = {n: z.read(n) for n in z.namelist()}
        def mutate(part, action):
            changed = dict(entries)
            changed[part] = action(changed[part])
            with zipfile.ZipFile(deck, 'w', zipfile.ZIP_DEFLATED) as z:
                for name, data in changed.items(): z.writestr(name, data)
        notes_part = 'ppt/notesSlides/notesSlide1.xml'
        def empty_notes(raw):
            node = ET.fromstring(raw)
            for t in node.findall('.//a:t', NS): t.text = ''
            return ET.tostring(node)
        mutate(notes_part, empty_notes)
        assert any('Empty notes' in e for e in check(sandbox))
        def remove_table(raw):
            node = ET.fromstring(raw)
            for parent in node.iter():
                for child in list(parent):
                    if child.tag == '{'+NS['a']+'}tbl': parent.remove(child)
            return ET.tostring(node)
        mutate('ppt/slides/slide4.xml', remove_table)
        assert any('No native table' in e for e in check(sandbox))
        chart_part = next(n for n in entries if '/charts/' in n and n.endswith('.xml') and '/_rels/' not in n)
        def change_chart(raw):
            node = ET.fromstring(raw)
            node.find('.//c:val//c:pt/c:v', NS).text = '999'
            return ET.tostring(node)
        mutate(chart_part, change_chart)
        assert any('Unexpected chart values' in e for e in check(sandbox))
        deck.write_bytes(original_deck)
        private = sandbox/'preferences.local.json'
        private.write_text('{}', encoding='utf-8')
        assert any('Private environment file' in e for e in check(sandbox))
        private.unlink()
        assert not check(sandbox), 'Restored package failed'
    return 10

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    errors = check(args.root)
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'Package checks passed: {len(REQUIRED)} required resources; links, preferences, SVG, native samples, notes and previews valid.')
    if args.self_test:
        print(f'Self-test passed: {self_test(args.root)} negative cases and restored baseline.')
    print('Scope: resource and sample-file structure only; no rendering, PowerPoint UI or scientific accuracy claim.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
