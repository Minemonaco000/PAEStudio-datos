"""Build an immutable, data-only channel. Changed datasets require a matching review record."""
from pathlib import Path
import argparse, datetime as dt, hashlib, json, re
ROOT = Path(__file__).resolve().parents[1]
def sha(data): return hashlib.sha256(data).hexdigest()
def load(path): return json.loads(Path(path).read_bytes())
def require(ok, message):
    if not ok: raise ValueError(message)
def date(value):
    parsed=dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
def validate_catalog(c):
    require(c['schemaVersion']==1 and isinstance(c['version'],str) and 0<len(c['version'])<100, 'catalog version')
    require(2026<=c['offerYear']<=c['targetYear']<=2100 and type(c['definitive']) is bool,'catalog years')
    date(c['publishedAt']);date(c['checkedAt'])
    for field in ['officialOffer','calendar']: require(c[field].startswith('https://'),'official URL')
    require(100<=c['generalMinAverage']<=1000 and 0<len(c['programs'])<=15000,'catalog size')
    seen=set();fields={'nem','ranking','cl','m1','m2','history','science'}
    for p in c['programs']:
        require(re.fullmatch(r'\d{5}',p['code']) and p['code'] not in seen and p['year']==c['offerYear'] and p['id']==str(p['year'])+'-'+p['code'],'program identity');seen.add(p['code'])
        require(p['status'] in ['verified','review'] and p['source'].startswith('https://'),'program source/status')
        require(all(isinstance(p[k],str) and 0<len(p[k])<500 for k in ['name','university','campus']),'program labels')
        w=p.get('weights')
        if w: require(set(w)==fields and all(type(v) in [int,float] and 0<=v<=100 for v in w.values()),'weights')
        if p['status']=='verified':
            require(w and 0<=p['specialWeight']<=100 and sum(w.values())-min(w['history'],w['science'])+p['specialWeight']==100,'weight total')
            require(not(w['history'] and w['science']) or w['history']==w['science'],'elective weights')
            require(all(type(p[k]) in [int,float] and 0<=p[k]<=1000 for k in ['minWeighted','minAverage']) and 0<=p['vacancies']<=100000,'threshold')
        for x in p['cutoffs']:
            require(2023<=x['year']<=c['targetYear'] and 100<=x['score']<=1000 and x['source'].startswith('https://'),'cutoff')
            if 'method' in x: require(x['method']=='mineduc-regular-selected-v1' and x['kind']=='selected' and x['year']==2026 and type(x['observations']) is int and x['observations']>0 and x['observations']==p.get('selectionStats',{}).get('regularSelected'),'cutoff aggregation')
        if 'selectionStats' in p:
            s=p['selectionStats'];require(type(s['year']) is int and 2023<=s['year']<c['offerYear'] and s['source'].startswith('https://'),'selection provenance');date(s['checkedAt'])
            require(all(type(s[k]) is int and 0<=s[k]<=100000 for k in ['regularVacancies','regularSelected']),'selection counts')
            require(type(s['filledRegularVacancies']) is bool and s['filledRegularVacancies']==(s['regularSelected']>=s['regularVacancies']),'selection capacity')
            require(isinstance(s['historicalName'],str) and 0<len(s['historicalName'])<500 and type(s['sourceRow']) is int and s['sourceRow']>=2,'selection attribution')
            average=s['lastSelectedMandatoryAverage'];require((average is None and s['regularSelected']==0) or (type(average) in [int,float] and 100<=average<=1000 and s['regularSelected']>0),'selection average')
    return c

def validate_tables(t):
    require(t['schemaVersion']==1 and isinstance(t['version'],str),'tables version');date(t['checkedAt'])
    ids=[e['id'] for e in t['editions']];require(0<len(ids)<=100 and len(ids)==len(set(ids)) and all(re.fullmatch(r'(invierno|regular)-20\d{2}',i) for i in ids),'editions')
    keys=set()
    for row in t['tables']:
        k=(row['edition'],row['subject']);require(k not in keys and k[0] in ids and k[1] in ['M1','M2','CL','HI','SC'],'table identity');keys.add(k)
        v=row['values'];require(type(row['maximum']) is int and 0<row['maximum']<=100 and len(v)==row['maximum']+1 and v[0]==100 and v[-1]==1000 and all(type(x) is int and 100<=x<=1000 for x in v) and v==sorted(v),'table values')
        require(row['source'].startswith('https://') and re.fullmatch('[a-f0-9]{64}',row['sourceSHA256']),'table provenance')
    require(len(keys)==5*len(ids),'missing subject table');return t

def build(data_dir, status_path, output_dir, review_path, now=None):
    data_dir,output_dir=Path(data_dir),Path(output_dir);review=load(review_path)
    raw={k:(data_dir/name).read_bytes() for k,name in [('catalog','catalog.json'),('tables','score-tables.json')]}
    catalog=validate_catalog(json.loads(raw['catalog']));tables=validate_tables(json.loads(raw['tables']))
    require(review.get('schemaVersion')==1 and review.get('decision')=='approved' and review.get('reason') and review.get('reviewer') and review.get('sourceURLs'),'Editorial approval missing')
    date(review['reviewedAt'])
    for k in raw: require(review[k+'SHA256']==sha(raw[k]),'Dataset changed without editorial review: '+k)
    status=load(status_path);require(status['catalogVersion']==catalog['version'],'Monitor/catalog version mismatch');date(status['checkedAt'])
    require(0<=status['checkedSources']<=status['totalSources'],'Monitor counts')
    previous=load(output_dir/'manifest.json') if (output_dir/'manifest.json').exists() else None
    refs={k:dict(file=('catalog' if k=='catalog' else 'score-tables')+'.'+sha(raw[k])+'.json',sha256=sha(raw[k]),bytes=len(raw[k])) for k in raw}
    public_status=dict(checkedAt=status['checkedAt'],checkedSources=status['checkedSources'],totalSources=status['totalSources'],pending=len(status['pending']),errors=len(status['errors']))
    minimum_app='2.46.0' if any('selectionStats' in p for p in catalog['programs']) else '2.45.0'
    if previous:
        old=load(output_dir/previous['catalog']['file']);require(catalog['offerYear']>=old['offerYear'] and date(catalog['publishedAt'])>=date(old['publishedAt']) and date(catalog['checkedAt'])>=date(old['checkedAt']),'catalog rollback')
        old_t=load(output_dir/previous['tables']['file']);require(date(tables['checkedAt'])>=date(old_t['checkedAt']) and set(e['id'] for e in old_t['editions'])<=set(e['id'] for e in tables['editions']),'tables rollback')
        require(date(status['checkedAt'])>=date(previous['status']['checkedAt']),'monitor rollback')
        if previous['catalog']==refs['catalog'] and previous['tables']==refs['tables'] and previous['status']==public_status and previous['minAppVersion']==minimum_app: return previous
    output_dir.mkdir(parents=True,exist_ok=True)
    for k,ref in refs.items():
        dest=output_dir/ref['file']
        if dest.exists(): require(dest.read_bytes()==raw[k],'immutable file was changed')
        else: dest.write_bytes(raw[k])
    manifest=dict(schemaVersion=1,sequence=previous['sequence']+1 if previous else 1,minAppVersion=minimum_app,publishedAt=now or dt.datetime.now(dt.timezone.utc).isoformat(),catalogVersion=catalog['version'],tablesVersion=tables['version'],**refs,status=public_status)
    # The Git commit publishes both data and manifest together; files themselves are immutable.
    (output_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,default=ROOT/'admissions');p.add_argument('--status',type=Path,default=ROOT/'.monitor/report.json');p.add_argument('--output',type=Path,default=ROOT/'channel/public');p.add_argument('--review',type=Path,default=ROOT/'admissions/feed-review.json');a=p.parse_args()
    print(json.dumps(build(a.data_dir,a.status,a.output,a.review),ensure_ascii=False,indent=2))
