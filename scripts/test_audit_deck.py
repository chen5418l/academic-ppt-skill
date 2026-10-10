"""Exercise observable failure detection on the bundled real 20-slide case."""
import copy
import json
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from audit_deck import Deck, NS, check


def main():
    root = Path(__file__).resolve().parents[1]
    file = root / 'examples/deepopf/deepopf-academic-v3.pptx'
    manifest = json.loads((file.parent / 'evidence.json').read_text(encoding='utf-8'))
    assert not check(file, manifest), 'Baseline must pass'
    original = Deck(file).parts
    passed = []
    with tempfile.TemporaryDirectory(prefix='academic-ppt-audit-') as folder:
        mutated = Path(folder) / 'mutated.pptx'

        def run(label, member, action, expected, compare=False):
            parts = dict(original)
            node = ET.fromstring(parts[member])
            action(node)
            parts[member] = ET.tostring(node, encoding='utf-8', xml_declaration=True)
            with zipfile.ZipFile(mutated, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, data in parts.items():
                    archive.writestr(name, data)
            errors = check(mutated, manifest, file if compare else None, ['results-speed'])
            assert any(expected in e for e in errors), (label, errors)
            passed.append(label)

        chart = next(n for n in original if n.endswith('/chart1.xml'))
        run('wrong chart number', chart,
            lambda n: setattr(n.find('.//c:val//c:pt/c:v', NS), 'text', '999'), 'chart data differ')
        def remove_tables(node):
            for parent in node.iter():
                for child in list(parent):
                    if child.tag == '{' + NS['a'] + '}tbl':
                        parent.remove(child)
        run('lost native table', 'ppt/slides/slide17.xml', remove_tables, 'missing native table')
        def remove_chart(node):
            for parent in node.iter():
                for child in list(parent):
                    if child.tag == '{' + NS['c'] + '}chart':
                        parent.remove(child)
        run('lost result figure', 'ppt/slides/slide15.xml', remove_chart, 'missing native chart')
        run('dropped slide', 'ppt/presentation.xml',
            lambda n: n.find('p:sldIdLst', NS).remove(list(n.find('p:sldIdLst', NS))[-1]), 'presentation order')
        def swap(node):
            items = node.find('p:sldIdLst', NS)
            a, b = list(items)[14:16]
            items.remove(a)
            items.insert(15, a)
        run('shuffled page order', 'ppt/presentation.xml', swap, 'presentation order')
        run('edit spilled into unrelated page', 'ppt/slides/slide2.xml',
            lambda n: setattr(n.find('.//a:t', NS), 'text', 'unrelated mutation'), 'unrelated slide', True)
        wrong = copy.deepcopy(manifest)
        wrong['slides'][14]['claims'][0]['source'] = 'not-a-source'
        assert any('unknown or incomplete source' in e for e in check(file, wrong))
        passed.append('unknown evidence source')
        wrong = copy.deepcopy(manifest)
        wrong['slides'][1]['required_objects'].append('nonexistent-anchor')
        assert any('missing or ambiguous object' in e for e in check(file, wrong))
        passed.append('missing stable object')
        image_page = next(s for s in manifest['slides'] if s.get('images'))
        wrong = copy.deepcopy(manifest)
        target = next(s for s in wrong['slides'] if s['id'] == image_page['id'])
        target['images'][0]['sha256'] = '0' * 64
        assert any('image content differs' in e for e in check(file, wrong))
        passed.append('changed bound scientific image')
        def remove_image(node):
            for parent in node.iter():
                for child in list(parent):
                    if child.tag == '{' + NS['p'] + '}pic':
                        parent.remove(child)
        run('lost scientific image', image_page['part'], remove_image, 'missing bound image')
    assert not check(file, manifest), 'Original remains valid'
    print(json.dumps({'status': 'passed', 'negative_cases': passed,
                      'scope': 'Observable binding and revision failures; no independent semantic or visual evaluation.'}, indent=2))


if __name__ == '__main__':
    main()
