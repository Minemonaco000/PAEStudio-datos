from pathlib import Path
import importlib.util, tempfile, json, shutil, unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('feed',ROOT/'admissions/feed.py');feed=importlib.util.module_from_spec(spec);spec.loader.exec_module(feed)
class FeedTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data=self.root/'admissions';self.data.mkdir();self.out=self.root/'public';self.status=self.root/'status.json';self.review=self.data/'feed-review.json'
  for n in ['catalog.json','score-tables.json','feed-review.json']:shutil.copyfile(ROOT/'admissions'/n,self.data/n)
  # The feed unit tests must not depend on a live monitor's last catalog version.
  self.status.write_text(json.dumps(dict(catalogVersion=feed.load(self.data/'catalog.json')['version'],checkedAt='2026-09-26T04:00:00Z',checkedSources=24,totalSources=24,pending=[],errors=[])))
 def tearDown(self):self.tmp.cleanup()
 def build(self):return feed.build(self.data,self.status,self.out,self.review,'2026-09-26T04:00:00Z')
 def test_roundtrip_and_idempotence(self):
  m=self.build();self.assertEqual(m,self.build());self.assertEqual(m['sequence'],1)
  self.assertEqual(m['minAppVersion'],'2.46.0')
  for k in ['catalog','tables']:
   raw=(self.out/m[k]['file']).read_bytes();self.assertEqual(feed.sha(raw),m[k]['sha256']);self.assertEqual(len(raw),m[k]['bytes'])
 def test_source_changes_only_publish_review_status(self):
  first=self.build();s=feed.load(self.status);s['pending']=[{'url':'https://demre.cl/changed'}];s['checkedAt']='2026-09-27T00:00:00Z';self.status.write_text(json.dumps(s));second=self.build();self.assertEqual(second['sequence'],2);self.assertEqual(first['catalog'],second['catalog']);self.assertEqual(second['status']['pending'],1)
 def test_unapproved_edit_rejected(self):
  c=feed.load(self.data/'catalog.json');c['programs'][0]['vacancies']+=1;(self.data/'catalog.json').write_text(json.dumps(c))
  with self.assertRaisesRegex(ValueError,'without editorial review'):self.build()
 def test_invalid_math_rejected(self):
  c=feed.load(self.data/'catalog.json');c['programs'][0]['weights']['m1']+=1
  with self.assertRaises(ValueError):feed.validate_catalog(c)
  t=feed.load(self.data/'score-tables.json');t['tables'][0]['values'][1]=1001
  with self.assertRaises(ValueError):feed.validate_tables(t)
 def test_missing_table_rejected(self):
  t=feed.load(self.data/'score-tables.json');t['tables'].pop()
  with self.assertRaises(ValueError):feed.validate_tables(t)
 def test_selection_validation_and_compatible_app(self):
  for key,value in [('regularSelected',-1),('lastSelectedMandatoryAverage',1001),('year',2027),('source','javascript:alert(1)')]:
   c=feed.load(self.data/'catalog.json');p=next(p for p in c['programs'] if 'selectionStats' in p);p['selectionStats'][key]=value
   with self.assertRaises(ValueError):feed.validate_catalog(c)
  first=self.build();older=dict(first,minAppVersion='2.45.0');(self.out/'manifest.json').write_text(json.dumps(older));second=self.build()
  self.assertEqual(second['sequence'],2);self.assertEqual(second['minAppVersion'],'2.46.0');self.assertEqual(second['catalog'],first['catalog'])
 def test_monitor_for_different_catalog_rejected(self):
  s=feed.load(self.status);s['catalogVersion']='older-catalog';self.status.write_text(json.dumps(s))
  with self.assertRaisesRegex(ValueError,'Monitor/catalog version mismatch'):self.build()
 def test_backwards_monitor_rejected(self):
  self.build();s=feed.load(self.status);s['checkedAt']='2020-01-01';self.status.write_text(json.dumps(s))
  with self.assertRaisesRegex(ValueError,'rollback'):self.build()
 def test_dates_preserve_the_instant_across_timezones(self):
  self.assertEqual(feed.date('2026-09-26T01:00:00-03:00'),feed.date('2026-09-26T04:00:00Z'))
  self.assertLess(feed.date('2026-09-26T05:00:00+02:00'),feed.date('2026-09-26T04:00:00Z'))
 def test_immutable_bytes_rejected(self):
  m=self.build();(self.out/m['catalog']['file']).write_text('{}')
  with self.assertRaises((ValueError,KeyError)):self.build()
if __name__=='__main__':unittest.main()
