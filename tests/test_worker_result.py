import json,tempfile,unittest
from pathlib import Path
from shared.worker_result import parse_result,ResultError
class WorkerResultTests(unittest.TestCase):
 def result(self):return {'schema_version':1,'job_id':'j','stage_id':'s','logical_slot_id':'slot','request_id':'r','worker_id':'p/w','effective_brief_sha256':'a'*64,'status':'ready-for-acceptance','conclusion':'done','requirements':[{'id':'R','status':'passed','evidence':['log']}],'review_verdict':None,'findings':[],'gaps':[],'uncertainties':[],'changes':[],'commands':[],'artifacts':[],'revision':None,'binding':{},'extra_work_requests':[],'metrics':{}}
 def test_complete_inline_and_hostile_json(self):
  v=self.result();expected={k:v[k] for k in ('job_id','stage_id','logical_slot_id','request_id','worker_id','effective_brief_sha256')}
  self.assertEqual(parse_result(json.dumps(v).encode(),expected)['kind'],'inline')
  for raw in (b'prefix {}',b'{"a":1,"a":2}',b'{"n":NaN}'):
   with self.assertRaises(ResultError):parse_result(raw,expected)
  v['findings']=[{'id':'F','severity':'major','scenario':'break','source_evidence':'log'}];v['review_verdict']='approve'
  with self.assertRaises(ResultError):parse_result(json.dumps(v).encode(),expected)
 def test_artifact_regular_hash_index_and_size(self):
  v=self.result();expected={k:v[k] for k in ('job_id','stage_id','logical_slot_id','request_id','worker_id','effective_brief_sha256')}
  with tempfile.TemporaryDirectory() as d:
   expected={**expected,'task_id':'t0'};root=Path(d);target=root/'artifacts/tasks/t0';target.mkdir(parents=True);raw=json.dumps(v).encode();(target/'full.json').write_bytes(raw)
   env={'schema_version':1,'artifact':{'path':'artifacts/tasks/t0/full.json','sha256':__import__('hashlib').sha256(raw).hexdigest(),'finding_count':0,'finding_ids':[]},'correlation':expected}
   self.assertEqual(parse_result(json.dumps(env).encode(),expected,root)['kind'],'artifact')
   with self.assertRaises(ResultError):parse_result(json.dumps(env).encode(),expected,root,1)

 def test_artifact_scope_correlation_symlink_fifo_and_inline_boundary(self):
  import hashlib,os
  v=self.result();expected={k:v[k] for k in ('job_id','stage_id','logical_slot_id','request_id','worker_id','effective_brief_sha256')}
  with tempfile.TemporaryDirectory() as d:
   expected={**expected,'task_id':'t0'};root=Path(d);raw=json.dumps(v).encode();target=root/'artifacts/tasks/t0/full.json';target.parent.mkdir(parents=True);target.write_bytes(raw)
   envelope={'schema_version':1,'artifact':{'path':'artifacts/tasks/t0/full.json','sha256':hashlib.sha256(raw).hexdigest(),'finding_count':0,'finding_ids':[]},'correlation':expected}
   self.assertEqual(parse_result(json.dumps(envelope).encode(),expected,root)['kind'],'artifact')
   envelope['correlation']={**expected,'request_id':'request-from-another-task'}
   with self.assertRaises(ResultError):parse_result(json.dumps(envelope).encode(),expected,root)
   envelope['correlation']=expected;target.unlink();target.symlink_to(root/'outside.json');(root/'outside.json').write_bytes(raw)
   with self.assertRaises(ResultError):parse_result(json.dumps(envelope).encode(),expected,root)
   target.unlink();os.mkfifo(target)
   with self.assertRaises(ResultError):parse_result(json.dumps(envelope).encode(),expected,root)
  oversized=self.result();oversized['conclusion']='word '*7000
  self.assertGreater(len(json.dumps(oversized).encode()),32768)
  with self.assertRaises(ResultError):parse_result(json.dumps(oversized).encode(),expected)
  with tempfile.TemporaryDirectory() as d:
   expected={**expected,'task_id':'t0'};root=Path(d);raw=json.dumps(v).encode();target=root/'artifacts/tasks/other/full.json';target.parent.mkdir(parents=True);target.write_bytes(raw)
   envelope={'schema_version':1,'artifact':{'path':'artifacts/tasks/other/full.json','sha256':hashlib.sha256(raw).hexdigest(),'finding_count':0,'finding_ids':[]},'correlation':expected}
   with self.assertRaises(ResultError):parse_result(json.dumps(envelope).encode(),expected,root)

 def test_full_result_rejects_wrong_types_and_missing_requirement_id(self):
  v=self.result();expected={k:v[k] for k in ('job_id','stage_id','logical_slot_id','request_id','worker_id','effective_brief_sha256')}
  for field,value in [('gaps',3),('uncertainties',False),('changes','wrong'),('commands',None),('artifacts',{}),('binding',[]),('metrics','wrong')]:
   bad=dict(v);bad[field]=value
   with self.assertRaises(ResultError):parse_result(json.dumps(bad).encode(),expected)
  bad=dict(v);bad['requirements']=[{'status':'passed','evidence':['log']}]
  with self.assertRaises(ResultError):parse_result(json.dumps(bad).encode(),expected)

 def test_expected_requirements_revision_binding_waivers_and_unknown_metric_evidence(self):
  v=self.result();v['revision']='rev-1';v['binding']={'snapshot':'before-check'}
  expected={k:v[k] for k in ('job_id','stage_id','logical_slot_id','request_id','worker_id','effective_brief_sha256')}
  expected.update(requirements=['R'],revision='rev-1',binding={'snapshot':'before-check'})
  self.assertEqual(parse_result(json.dumps(v).encode(),expected)['result']['revision'],'rev-1')
  for field,value in (('requirements',[]),('revision','other'),('binding',{'snapshot':'after-check'})):
   bad=dict(v);bad[field]=value
   with self.assertRaises(ResultError):parse_result(json.dumps(bad).encode(),expected)
  waived=dict(v);waived['requirements']=[{'id':'R','status':'waived','evidence':['waiver'],'reason':'not authorized'}]
  with self.assertRaises(ResultError):parse_result(json.dumps(waived).encode(),expected)
  owner={'id':'owner-1','quote':'waive R','source':'fixture owner','source_sha256':'a'*64,'scope':'waiver:t0','requirement_ids':['R']}
  waived['requirements'][0]['owner_evidence']=owner
  expected.update(owner_waivers=[owner],waivable_requirements=['R'])
  self.assertEqual(parse_result(json.dumps(waived).encode(),expected)['result']['requirements'][0]['status'],'waived')
  missing_metric=dict(v);missing_metric['metrics']={'tokens':None}
  with self.assertRaises(ResultError):parse_result(json.dumps(missing_metric).encode(),expected)
  evidenced_metric=dict(v);evidenced_metric['metrics']={'tokens':{'value':None,'reason':'provider did not report token usage'}}
  self.assertEqual(parse_result(json.dumps(evidenced_metric).encode(),expected)['result']['metrics']['tokens']['value'],None)

if __name__=='__main__':unittest.main()
