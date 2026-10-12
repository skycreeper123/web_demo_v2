from pathlib import Path
import hashlib
import json
import re
import urllib.request
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent

def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)

rows = []
for repo in json.loads((ROOT / 'new_inventory.json').read_text(encoding='utf-8-sig')):
    for path in repo['paths']:
        relative = 'reference_workflows/' + repo['repo'].split('/')[0] + '/' + Path(path).name
        destination = ROOT / relative
        url = f"https://raw.githubusercontent.com/{repo['repo']}/{repo['commit']}/{quote(path, safe='/')}"
        request = urllib.request.Request(url, headers={'User-Agent': 'Research-reference-check'})
        data = urllib.request.urlopen(request, timeout=60).read()
        graph = json.loads(data)
        ui_format = isinstance(graph.get('nodes'), list)
        api_format = bool(graph) and all(isinstance(n, dict) and 'class_type' in n for n in graph.values())
        assert ui_format or api_format, path
        modifications = []
        source_hash = hashlib.sha256(data).hexdigest()
        if Path(path).name == 'f5_tts.json':
            graph['24']['inputs']['text'] = 'This is a short sample of my voice recorded in a quiet room.'
            graph['32']['inputs']['text'] = 'Today we are testing a short video made from real footage and an artificial background.'
            graph['36']['inputs']['audio'] = 'reference_voice.wav'
            graph['37']['inputs']['filename_prefix'] = 'research/voice'
            modifications = ['Replaced sample transcript and target speech with neutral original text.',
                             'Replaced identity-specific audio filename and output prefix. Supply your own audio and its exact transcript.']
            data = json.dumps(graph, ensure_ascii=False, indent=2).encode('utf-8')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        nodes = [n for n in walk(graph) if isinstance(n.get('type'), str) and 'id' in n and ('inputs' in n or 'widgets_values' in n)] if ui_format else list(graph.values())
        model_names = sorted(set(s for s in strings(graph) if len(s) < 180 and re.search(r'\.(safetensors|gguf|pth|pt|ckpt|onnx)$', s, re.I)))
        rows.append({'repo': repo['repo'], 'commit': repo['commit'], 'path': path,
                     'source': url, 'local': relative, 'sha256': hashlib.sha256(data).hexdigest(),
                     'source_sha256': source_hash, 'modifications': modifications,
                     'format': 'ui' if ui_format else 'api',
                     'bytes': len(data), 'top_level_nodes': len(graph['nodes']) if ui_format else len(graph),
                     'node_types_including_subgraphs': sorted(set(n.get('type', n.get('class_type')) for n in nodes)),
                     'model_names': model_names, 'gpu_executed': False})
        print(json.dumps({'file': relative, 'nodes': len(nodes), 'models': model_names}, ensure_ascii=False))
(ROOT / 'reference_manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
