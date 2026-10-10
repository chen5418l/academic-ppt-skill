"""Check a PPTX against an optional evidence manifest and a scoped previous version.

Standard library only. This is binding/structure verification, not scientific or visual QA.
"""
import argparse
import hashlib
import json
import posixpath
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
      'd': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}


def relation_part(part):
    folder, name = posixpath.split(part)
    return posixpath.join(folder, '_rels', name + '.rels')


class Deck:
    def __init__(self, file):
        with zipfile.ZipFile(file) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError('Corrupt member: ' + bad)
            self.parts = {name: archive.read(name) for name in archive.namelist()}
        for name, raw in self.parts.items():
            if name.endswith(('.xml', '.rels')):
                ET.fromstring(raw)
        root = self.xml('ppt/presentation.xml')
        rels = self.rels('ppt/presentation.xml')
        self.order = [rels[s.attrib['{' + NS['d'] + '}id']]
                      for s in root.findall('./p:sldIdLst/p:sldId', NS)]

    def xml(self, part):
        return ET.fromstring(self.parts[part])

    def rels(self, part):
        raw = self.parts.get(relation_part(part))
        if raw is None:
            return {}
        out = {}
        for rel in ET.fromstring(raw):
            if rel.get('TargetMode') == 'External':
                continue
            target = rel.attrib['Target']
            resolved = (target.lstrip('/') if target.startswith('/') else
                        posixpath.normpath(posixpath.join(posixpath.dirname(part), target)))
            if resolved.startswith('../') or resolved not in self.parts:
                raise ValueError('Missing or invalid relation: ' + resolved)
            out[rel.attrib['Id']] = resolved
        return out

    def closure(self, part):
        found, pending = set(), [part]
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            relpart = relation_part(current)
            if relpart in self.parts:
                found.add(relpart)
            pending.extend(p for p in self.rels(current).values() if p not in found)
        return {p: hashlib.sha256(self.parts[p]).hexdigest() for p in sorted(found)}

    def text(self, part):
        return '\n'.join(n.text or '' for n in self.xml(part).findall('.//a:t', NS))


def check(file, manifest, before=None, allow=()):
    errors = []
    if manifest.get('schema_version') != 1:
        return ['Unsupported manifest version']
    pages = manifest.get('slides', [])
    ids = [s['id'] for s in pages]
    if len(ids) != len(set(ids)):
        errors.append('Duplicate semantic slide IDs')
    sources = manifest.get('sources', {})
    deck = Deck(file)
    if deck.order != [s['part'] for s in pages]:
        errors.append('Slide count or presentation order differs from manifest')
    for page in pages:
        label, part = page['id'], page['part']
        if part not in deck.parts:
            errors.append(label + ': missing slide')
            continue
        root = deck.xml(part)
        visible = deck.text(part)
        notes = [p for p in deck.rels(part).values() if p.startswith('ppt/notesSlides/') and p.endswith('.xml')]
        note_text = '\n'.join(deck.text(p) for p in notes)
        if not note_text.strip():
            errors.append(label + ': empty or missing notes')
        if page['title'] not in visible:
            errors.append(label + ': title missing')
        names = [n.get('name') for n in root.findall('.//p:cNvPr', NS)]
        for name in page.get('required_objects', []):
            if names.count(name) != 1:
                errors.append(label + ': missing or ambiguous object ' + name)
        pictures = root.findall('.//p:pic', NS)
        for spec in page.get('images', []):
            index = spec.get('index', -1)
            if not isinstance(index, int) or index < 0 or index >= len(pictures):
                errors.append(label + ': missing bound image')
                continue
            blip = pictures[index].find('.//a:blip', NS)
            rid = None if blip is None else blip.get('{' + NS['d'] + '}embed')
            media = deck.rels(part).get(rid)
            if not media or hashlib.sha256(deck.parts[media]).hexdigest() != spec.get('sha256'):
                errors.append(label + ': image content differs')
        for claim in page.get('claims', []):
            source = sources.get(claim.get('source'))
            if not source or not all(source.get(k) for k in ('title', 'url', 'version')):
                errors.append(label + ': unknown or incomplete source')
            if not claim.get('locator') or claim.get('status') not in ('reported', 'calculated', 'interpretation', 'hypothesis', 'pending'):
                errors.append(label + ': missing locator or invalid evidence status')
            if claim.get('text', '') not in visible + '\n' + note_text or not claim.get('text'):
                errors.append(label + ': bound claim missing')
        tables = root.findall('.//a:tbl', NS)
        for spec in page.get('tables', []):
            if spec['index'] >= len(tables):
                errors.append(label + ': missing native table')
                continue
            actual = [[''.join(t.text or '' for t in cell.findall('.//a:t', NS))
                       for cell in row.findall('a:tc', NS)]
                      for row in tables[spec['index']].findall('a:tr', NS)]
            if actual != spec['values']:
                errors.append(label + ': native table cells differ')
        charts = root.findall('.//c:chart', NS)
        for spec in page.get('charts', []):
            if spec['index'] >= len(charts):
                errors.append(label + ': missing native chart')
                continue
            chart_part = deck.rels(part)[charts[spec['index']].attrib['{' + NS['d'] + '}id']]
            series = deck.xml(chart_part).findall('.//c:ser', NS)
            values = [[float(v.text) for v in item.findall('.//c:val//c:pt/c:v', NS)] for item in series]
            categories = [[''.join(v.itertext()) for v in item.findall('.//c:cat//c:pt/c:v', NS)] for item in series]
            if values != spec['values'] or any(c != spec['categories'] for c in categories):
                errors.append(label + ': native chart data differ')
    if before:
        old = Deck(before)
        if old.order != deck.order:
            errors.append('Local revision changed slide count or order')
        unknown = set(allow) - set(ids)
        if unknown:
            errors.append('Unknown allowed slide IDs: ' + ', '.join(sorted(unknown)))
        for page in pages:
            part = page['part']
            if page['id'] not in allow and part in old.parts and part in deck.parts:
                if old.closure(part) != deck.closure(part):
                    errors.append(page['id'] + ': unrelated slide or associated part changed')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pptx', type=Path)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--allow-slide', action='append', default=[])
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        errors = check(args.pptx, manifest, args.before, args.allow_slide)
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError, TypeError, ValueError, IndexError) as exc:
        errors = ['Cannot verify: ' + str(exc)]
    print(json.dumps({'status': 'failed' if errors else 'passed', 'errors': errors,
                      'scope': 'Bindings, package and revision scope only; no source, visual or player verification.'}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
