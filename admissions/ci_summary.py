"""Summarize the source monitor without editing admissions rules or student data."""
import json,os
from pathlib import Path
p=Path('.monitor/report.json')
if not p.exists():
    print('::error::No se generó un informe de revisión.')
    raise SystemExit(1)
r=json.loads(p.read_text())
lines=['# Revisión de Mi ingreso',r['checkedAt'],r['message'],f"Fuentes consultadas: {r['checkedSources']}/{r['totalSources']}", '']
for title,key in [('Cambios pendientes de revisión','pending'),('Fuentes que no se pudieron consultar','errors')]:
    lines.append('## '+title)
    for x in r[key]:lines.append('- '+x['source']+' — '+x['url']+(' — '+x['error'] if key=='errors' else ''))
    if not r[key]:lines.append('Ninguno.')
lines+=['','El monitor no modifica ponderaciones, cortes ni puntajes. Una nueva publicación debe contrastarse antes de incorporarla al catálogo.']
summary='\n'.join(lines)+'\n'
if os.getenv('GITHUB_STEP_SUMMARY'):Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(summary)
else:print(summary)
if r['pending']:print('::warning::Hay cambios en fuentes oficiales pendientes de revisión.')
if r['errors']:print('::warning::La revisión fue parcial; consulta el informe antes de afirmar vigencia.')
