"""Read public admissions sources. Never replace verified rules with unreviewed data.

This monitor writes a separate runtime status beside each desktop entry point.
It does not edit the app, its release ZIP, or any browser/progress data.

La app lee el estado con una ruta RELATIVA al HTML ('PAEStudio-v2-admision-estado.js'; si falta,
usa 'PAEStudio-v2-recursos/admissions/update-status.js', que es un recurso administrado por la
entrega y verificado por SHA-256, por lo que este monitor nunca lo escribe). Por eso el archivo de
estado debe quedar junto a '~/Desktop/PAEStudio v2.html': se escribe EN SITIO (mismo inodo, sin
temporal + rename, para que iCloud Drive no cree copias "<nombre> N") y queda oculto con
chflags hidden para que el Escritorio siga ordenado.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'admissions'
STATUS_NAME = 'PAEStudio-v2-admision-estado.js'
DESKTOP = Path.home() / 'Desktop'
# (carpeta, HTML de entrada, ocultar el archivo de estado)
DESKTOP_ENTRIES = [(DESKTOP, 'PAEStudio v2.html', True),
                   (DESKTOP / 'Personal/PAEStudio/Instalación/PAEStudio v2', 'index.html', False)]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as f:
            temporary = Path(f.name)
            f.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_in_place(path, text):
    """Overwrite path keeping its inode (iCloud Drive then records a new version, not a name clash)."""
    data = text.encode('utf-8')
    existed = path.exists() or path.is_symlink()
    if existed:
        assert path.is_file() and not path.is_symlink(), f'Not a regular file: {path}'
        flags = os.O_WRONLY | os.O_TRUNC
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
    with os.fdopen(descriptor, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(path, 0o644)
    assert path.read_bytes() == data, f'Status verification failed: {path}'


def hide(path):
    if not path.lstat().st_flags & stat.UF_HIDDEN:
        subprocess.run(['/usr/bin/chflags', 'hidden', str(path)], check=True, capture_output=True)
    assert path.lstat().st_flags & stat.UF_HIDDEN, f'Status file is not hidden: {path}'


def sources(catalog):
    targets = [dict(id='demre-offer', name='Oferta DEMRE '+str(catalog['offerYear']), url=catalog['officialOffer'], kind='pdf'),
               dict(id='demre-next', name='Publicaciones DEMRE '+str(catalog['targetYear']), url='https://demre.cl/publicaciones/listado-'+str(catalog['targetYear']), kind='listing')]
    for i, url in enumerate(sorted({c['source'] for p in catalog['programs'] for c in p['cutoffs']})):
        target = dict(id='cutoff-'+str(i), name=urllib.parse.urlparse(url).hostname, url=url, kind='html')
        if 'admision.uc.cl/' in url:
            target.update(url='https://admision.uc.cl/htdocs/cms/wp-admin/admin-ajax.php', kind='uc',
                          form=dict(action='calculateScore', simulador='23483', nem='850', ranking='900', lectora='800', m1='900', historia='700', ciencias='850', m2='750'))
        if urllib.parse.urlparse(url).hostname in ('fcm.usach.cl','www.fcm.usach.cl'):
            target['kind']='usach-cutoffs'
        targets.append(target)
    for i, source in enumerate(catalog.get('cutoffSource', {}).get('files', [])):
        targets.append(dict(id='cutoff-dataset-'+str(i),name='Mineduc '+source['name'],
            url=source['source'],kind='rar',baselineHash=source['sha256']))
    score_tables = json.loads((DATA/'score-tables.json').read_text())
    archive = DATA/'sources/score-tables'
    index = dict(id='score-index', name='Nuevas tablas de puntajes DEMRE', url=score_tables['index'], kind='score-index')
    index['baselineHash'] = fingerprint(index, (archive/'index.html').read_bytes())
    targets.append(index)
    for table in score_tables['tables']:
        target = dict(id='score-'+table['edition']+'-'+table['subject'], name='Tabla '+table['subject']+' '+table['edition'], url=table['source'], kind='html')
        target['baselineHash'] = fingerprint(target, (archive/(table['source'].rsplit('/',1)[1]+'.html')).read_bytes())
        targets.append(target)
    return targets


def fingerprint(spec, data):
    if spec['kind'] == 'rar':
        if not data.startswith(b'Rar!\x1a\x07'): raise ValueError('La fuente no devolvió una base RAR.')
        return digest(data)
    if spec['kind'] == 'pdf':
        if not data.startswith(b'%PDF-'): raise ValueError('La fuente no devolvió un PDF.')
        return digest(data)
    text = data.decode('utf-8')
    if spec['kind'] == 'uc':
        text = json.loads(text)['data']['desktop']
        if '12058' not in text: raise ValueError('Cambió el formato del simulador UC.')
    if spec['kind'] == 'usach-cutoffs':
        plain=re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', text)))
        rows=re.findall(r'(Primer|Último)\s+matriculado\s+(20\d{2})\s*:\s*(\d{3,4}(?:[.,]\d+)?)', plain, re.I)
        if len(rows)<2: raise ValueError('No se identificaron los cortes de matrícula USACH; revisar el formato de la fuente.')
        return digest(json.dumps(rows,ensure_ascii=False).encode())
    if spec['kind'] == 'listing':
        # Only admission-offer links matter, not changes in menus or news.
        links = re.findall(r'href=[\"\']([^\"\']+)[\"\']', text, re.I)
        offers = sorted({unescape(link) for link in links if 'oferta' in link.lower() and ('carrera' in link.lower() or 'definitiva' in link.lower())})
        if len(text) < 1000 or 'demre' not in text.lower(): raise ValueError('Listado DEMRE incompleto.')
        return digest(json.dumps(offers, ensure_ascii=False).encode())
    if spec['kind'] == 'score-index':
        links = sorted(set(re.findall(r'tabla-transformacion-puntajes-paes-(?:invierno|regular)-p\d{4}-[a-z0-9-]+', text)))
        if len(links) < 5: raise ValueError('Índice de tablas incompleto.')
        return digest(json.dumps(links).encode())
    text = re.sub(r'<(script|style)\b[^>]*>.*?</\1\s*>', '', text, flags=re.I | re.S)
    tables = re.findall(r'<table\b[^>]*>.*?</table\s*>', text, re.I | re.S)
    if tables: text = '\n'.join(tables)
    text = re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', text))).strip()
    if len(text) < 150 or re.search(r'verify you are human|just a moment|access denied|captcha challenge', text, re.I):
        raise ValueError('Fuente incompleta o no disponible para consulta automática.')
    return digest(text.encode())


def fetch(spec, previous):
    headers = {'User-Agent':'PAEStudio-admissions-check/1.0', 'Accept':'*/*'}
    for key, header in [('etag','If-None-Match'), ('modified','If-Modified-Since')]:
        if previous.get(key) and 'form' not in spec: headers[header] = previous[key]
    body = urllib.parse.urlencode(spec['form']).encode() if 'form' in spec else None
    request = urllib.request.Request(spec['url'], data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = response.read(24*1024*1024+1)
            if len(data)>24*1024*1024: raise ValueError('Fuente demasiado grande.')
            return dict(hash=fingerprint(spec,data), etag=response.headers.get('ETag'), modified=response.headers.get('Last-Modified'))
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and previous.get('hash'): return previous
        raise
    except urllib.error.URLError as exc:
        # On macOS, system curl validates UBB's certificate chain with the OS
        # trust store, while the bundled Python trust store lacks its issuer.
        # Keep certificate verification enabled and only retry public GETs.
        curl=Path('/usr/bin/curl')
        if 'CERTIFICATE_VERIFY_FAILED' not in str(exc) or body is not None or not curl.is_file():
            raise
        data=subprocess.check_output([str(curl),'--fail','--silent','--show-error',
            '--location','--max-time','25','--max-filesize',str(24*1024*1024),
            '--user-agent',headers['User-Agent'],spec['url']],timeout=30)
        if len(data)>24*1024*1024: raise ValueError('Fuente demasiado grande.')
        return dict(hash=fingerprint(spec,data),etag=None,modified=None)


def evaluate(catalog, targets, observations, previous, now):
    baseline = dict(previous.get('baseline', {}))
    baseline['demre-offer'] = catalog['sourceSHA256']
    changed, errors, successful = [], [], {}
    for spec, observation in zip(targets, observations):
        sid = spec['id']
        if spec.get('baselineHash'): baseline[sid] = spec['baselineHash']
        if isinstance(observation, Exception):
            errors.append(dict(source=spec['name'], url=spec['url'], error=str(observation)[:250]))
            continue
        successful[sid] = observation
        # First observations of secondary sources establish a monitor baseline;
        # they do not certify or silently refresh the admissions catalogue.
        if sid not in baseline: baseline[sid] = observation['hash']
        if observation['hash'] != baseline[sid]: changed.append(dict(source=spec['name'],url=spec['url']))
    prior_pending = previous.get('pending', [])
    for pending in prior_pending:
        if pending not in changed: changed.append(pending)
    if changed:
        message = 'Se detectaron cambios en fuentes oficiales. Se conservan el catálogo y las tablas de puntajes verificados; las novedades requieren revisión antes de incorporarse.'
    elif errors:
        message = 'Revisión parcial: no se pudieron consultar todas las fuentes. Se conserva el catálogo verificado; no se puede confirmar que siga siendo el más reciente.'
    else:
        message = 'La revisión no detectó cambios en las fuentes vigiladas. Se conserva el catálogo verificado de admisión '+str(catalog['offerYear'])+'.'
    return dict(schemaVersion=1, checkedAt=now, message=message, automatic=True,
                catalogVersion=catalog['version'], verifiedCatalogueAt=catalog['checkedAt'],
                baseline=baseline, observations={**previous.get('observations',{}),**successful},
                pending=changed, errors=errors, checkedSources=len(successful), totalSources=len(targets))


def run(publish=False, report_path=None, output_dir=None):
    catalog = json.loads((DATA/'catalog.json').read_text())
    report_path = Path(report_path) if report_path else DATA/'monitor-report.json'
    output_dir = Path(output_dir) if output_dir else ROOT/'release'
    previous = json.loads(report_path.read_text()) if report_path.exists() else {}
    if previous.get('catalogVersion') != catalog['version']: previous = {}
    targets = sources(catalog)
    def check(spec):
        try: return fetch(spec, previous.get('observations',{}).get(spec['id'],{}))
        except Exception as exc: return exc
    with ThreadPoolExecutor(max_workers=4) as pool: observations = list(pool.map(check,targets))
    report = evaluate(catalog, targets, observations, previous, datetime.now(timezone.utc).isoformat())
    atomic(report_path,json.dumps(report,ensure_ascii=False,indent=2))
    # This sidecar is deliberately outside managed release assets: a scheduled
    # status check must not invalidate the signed-off release/ZIP checksums.
    public = {k:report[k] for k in ['schemaVersion','checkedAt','message','automatic','catalogVersion','pending','errors','checkedSources','totalSources']}
    js = 'window.PAES_ADMISSIONS_UPDATE_STATUS='+json.dumps(public,ensure_ascii=False).replace('</','<\\/')+';\n'
    atomic(output_dir/STATUS_NAME,js)
    if publish:
        for folder, entry, hidden in DESKTOP_ENTRIES:
            if (folder/entry).is_file():
                write_in_place(folder/STATUS_NAME,js)
                if hidden: hide(folder/STATUS_NAME)
        # Daily safeguard: keep the resources folder hidden in Finder (flag only; content untouched).
        for resources in [DESKTOP/'PAEStudio-v2-recursos', DESKTOP/'PAEStudio-recursos']:
            if resources.is_dir() and not resources.is_symlink(): hide(resources)
    print(json.dumps({k:public[k] for k in ['message','checkedAt','checkedSources','totalSources']},ensure_ascii=False))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish-desktop', action='store_true')
    parser.add_argument('--state', type=Path, help='Archivo persistente con el estado de las fuentes.')
    parser.add_argument('--output-dir', type=Path, help='Directorio del estado público; no contiene progreso de estudiantes.')
    args=parser.parse_args()
    report=run(args.publish_desktop,args.state,args.output_dir)
    if report['checkedSources']==0: raise SystemExit(2)
