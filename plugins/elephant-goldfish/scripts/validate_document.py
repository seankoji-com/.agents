#!/usr/bin/env python3
"""Run existing content-bound handoff provenance/readiness checks."""
import argparse,json,subprocess,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shared.validator_observations import read_object,observation
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',default='thinking');p.add_argument('--slug',required=True);p.add_argument('--mode',choices=['handoff','factual','cold-read'],default='handoff');p.add_argument('--input');a=p.parse_args();script=Path(__file__).resolve().parent
 if a.mode=='handoff':
  checks=[[sys.executable,str(script/'thinking_state.py'),'--root',a.root,'gate',a.slug,'--require','discovery,spec,handoff'],[sys.executable,str(script/'render_handoff.py'),a.slug,'--root',a.root,'--check']]
  runs=[subprocess.run(c,capture_output=True,text=True) for c in checks];ok=all(r.returncode==0 for r in runs);evidence=[{'argv':c,'exit_code':r.returncode,'output':r.stdout[-2000:]} for c,r in zip(checks,runs)]
 elif a.mode in ('factual','cold-read'):
  try:
   f=Path(a.input);d,input_sha256=read_object(f)
   declared=Path(a.root).absolute()/a.slug
   document=Path(d['document_path']).absolute()
   if not document.is_relative_to(declared) or document==declared or '..' in Path(a.slug).parts or Path(a.slug).is_absolute():raise ValueError('observation document differs from declared slug scope')
   doc_sha256=hashlib.sha256(__import__('core.jobs.store',fromlist=['_regular'])._regular(document)).hexdigest()
   if d.get('document_sha256')!=doc_sha256:raise ValueError('observation document hash differs')
   if a.mode=='factual':
    rows=d.get('claims',[])
    def valid(r):
     if not isinstance(r,dict) or r.get('outcome') not in ('confirmed','refuted','unknown') or not r.get('claim_id') or not r.get('evidence'):return False
     return all(observation(e,'factual-claim').get('document_sha256')==doc_sha256 and observation(e,'factual-claim').get('claim_id')==r['claim_id'] and observation(e,'factual-claim').get('outcome')==r['outcome'] for e in r['evidence'])
    ok=d.get('kind')=='factual-observation' and bool(rows) and all(valid(r) for r in rows) and not any(r['outcome']=='unknown' for r in rows)
   else:
    document=Path(d['document_path']);_,doc_sha256=read_object(document) if document.suffix=='.json' else (None,hashlib.sha256(__import__('core.jobs.store',fromlist=['_regular'])._regular(document)).hexdigest())
    ok=(d.get('kind')=='cold-read-observation' and d.get('document_sha256')==doc_sha256 and d.get('verdict')=='ready' and bool(d.get('evidence')) and all(observation(e,'cold-read').get('document_sha256')==doc_sha256 and observation(e,'cold-read').get('verdict')=='ready' for e in d['evidence']))
   evidence=[{'observation_file':str(f),'sha256':input_sha256,'kind':d.get('kind'),'coverage':len(d.get('claims',d.get('evidence',[])))}]
   if a.mode=='factual':
    author_file=document.parent/'document-authors.json'
    try:
     author_records=json.loads(author_file.read_text()) if not author_file.is_symlink() else {}
     author_record=author_records.get(doc_sha256) if isinstance(author_records,dict) else None
    except (OSError,ValueError):author_record=None
    evidence[0]['author_independence']='unverified: author unrecorded' if not isinstance(author_record,dict) or author_record.get('unknown') else 'unverified: checker identity is not bound to this validation'
  except Exception as exc:ok=False;evidence=[{'reason':f'explicit {a.mode} coordinator observation is missing or invalid: {exc}'}]
 else:ok=False;evidence=[{'reason':'unsupported mode'}]
 out={'accepted':ok,'mode':a.mode,'requirement_outcomes':{'workflow-observation':{'status':'passed' if ok else 'unverified','evidence':evidence}}};print(json.dumps(out,sort_keys=True));return 0 if ok else 1
if __name__=='__main__':sys.exit(main())
