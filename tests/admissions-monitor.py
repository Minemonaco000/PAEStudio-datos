import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('monitor',Path(__file__).resolve().parents[1]/'admissions/check_sources.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.catalog=dict(sourceSHA256='verified',offerYear=2026,version='test',checkedAt='yesterday')
        self.targets=[dict(id='demre-offer',name='DEMRE',url='https://demre.cl/offer.pdf')]

    def test_changed_source_never_mutates_the_catalogue(self):
        report=m.evaluate(self.catalog,self.targets,[dict(hash='changed')],{},'today')
        self.assertEqual(len(report['pending']),1)
        self.assertEqual(self.catalog['sourceSHA256'],'verified')
        self.assertEqual(report['baseline']['demre-offer'],'verified')

    def test_failed_check_is_not_a_false_freshness_claim(self):
        report=m.evaluate(self.catalog,self.targets,[TimeoutError('offline')],{},'today')
        self.assertEqual(report['checkedSources'],0)
        self.assertEqual(len(report['errors']),1)
        self.assertIn('no se puede confirmar',report['message'])

    def test_pending_changes_survive_a_later_network_failure(self):
        report=m.evaluate(self.catalog,self.targets,[dict(hash='changed')],{},'today')
        later=m.evaluate(self.catalog,self.targets,[TimeoutError('offline')],report,'tomorrow')
        self.assertEqual(later['pending'],report['pending'])

    def test_only_offer_links_change_the_demre_listing_fingerprint(self):
        target=dict(kind='listing')
        base='<html>DEMRE'+(' '*1000)+'<a href="/2027-oferta-carreras.pdf">Oferta</a></html>'
        self.assertEqual(m.fingerprint(target,base.encode()),m.fingerprint(target,base.replace('Oferta</a>','Oferta definitiva</a>').encode()))
        self.assertNotEqual(m.fingerprint(target,base.encode()),m.fingerprint(target,base.replace('2027-oferta','2027-nueva-oferta').encode()))

    def test_conversion_index_detects_new_editions_without_menu_noise(self):
        base=' '.join('tabla-transformacion-puntajes-paes-invierno-p2027-'+name for name in ['m1','m2','ciencias','hycsoc','competencia-lectora'])
        target=dict(kind='score-index')
        self.assertEqual(m.fingerprint(target,base.encode()),m.fingerprint(target,('New menu '+base).encode()))
        self.assertNotEqual(m.fingerprint(target,base.encode()),m.fingerprint(target,(base+' tabla-transformacion-puntajes-paes-regular-p2027-m1').encode()))
        with self.assertRaises(ValueError): m.fingerprint(target,b'Incomplete HTML')

    def test_score_source_is_compared_with_reviewed_evidence_on_first_check(self):
        target=dict(id='score-m1',name='M1',url='https://demre.cl/table',baselineHash='reviewed')
        report=m.evaluate(self.catalog,[target],[dict(hash='new')],{},'today')
        self.assertEqual(report['baseline']['score-m1'],'reviewed')
        self.assertEqual(len(report['pending']),1)

    def test_usach_cutoffs_outside_a_social_media_layout_table(self):
        spec=dict(kind='usach-cutoffs')
        page='<table><tr><td>Redes sociales</td></tr></table><p>Primer matriculado 2026: 960,7</p><p>Último matriculado 2026: 937,8</p>'
        self.assertEqual(m.fingerprint(spec,page.encode()),m.fingerprint(spec,('Menú nuevo'+page).encode()))
        self.assertNotEqual(m.fingerprint(spec,page.encode()),m.fingerprint(spec,page.replace('937,8','939,0').encode()))
        with self.assertRaises(ValueError):m.fingerprint(spec,b'<table>Redes sociales</table>')

    def test_monitor_covers_all_fifteen_tables_and_the_discovery_index(self):
        catalog=__import__('json').loads((m.DATA/'catalog.json').read_text())
        targets=m.sources(catalog)
        self.assertEqual(len([s for s in targets if s['id'].startswith('score-')]),16)
        self.assertEqual(len(targets),18+len({c['source'] for p in catalog['programs'] for c in p['cutoffs']})+len(catalog.get('cutoffSource',{}).get('files',[])))

    def test_mineduc_archive_fingerprint_verifies_binary_content(self):
        spec=dict(kind='rar')
        source=b'Rar!\x1a\x07\x00verified source'
        self.assertEqual(m.fingerprint(spec,source),m.digest(source))
        self.assertNotEqual(m.fingerprint(spec,source),m.fingerprint(spec,source+b'changed'))
        with self.assertRaises(ValueError):m.fingerprint(spec,b'<html>service unavailable</html>')


if __name__=='__main__': unittest.main()
