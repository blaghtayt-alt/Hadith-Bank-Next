#!/usr/bin/env python3
"""Fail-closed pre-switch gate for commit-pinned, cross-origin content-addressed fallback objects."""
import argparse,concurrent.futures,datetime,hashlib,json,pathlib,re,subprocess,sys,time,urllib.error,urllib.request
ap=argparse.ArgumentParser()
ap.add_argument('--mode',choices=['chunk','gate'],required=True)
ap.add_argument('--manifest',required=True);ap.add_argument('--manifest-sha256',required=True)
ap.add_argument('--commit',required=True);ap.add_argument('--tag',required=True);ap.add_argument('--receipts',required=True)
ap.add_argument('--start',type=int);ap.add_argument('--end',type=int)
ap.add_argument('--verify-only',action='store_true',help='Recheck complete gate without writing a new receipt')
a=ap.parse_args()
if not re.fullmatch(r'[0-9a-f]{40}',a.commit) or a.commit=='0'*40:raise ValueError('invalid retained commit')
if a.tag!='retain-'+a.commit:raise ValueError('tag must be retain-<full commit>')
raw=pathlib.Path(a.manifest).read_bytes();mh=hashlib.sha256(raw).hexdigest()
if mh!=a.manifest_sha256:raise ValueError('manifest SHA-256 mismatch')
m=json.loads(raw);rid=m.get('release_id');root=m.get('release_root')
if not re.fullmatch(r'[0-9a-f]{64}',rid or '') or root!='/Hadith-Bank-data/releases/'+rid+'/':raise ValueError('invalid release root')
rows=m.get('rows');assert isinstance(rows,list)
targets=[];seen=set()
for row in rows:
 path=row['new_url_path'];digest=row['wire_sha256'];size=row['wire_bytes']
 if not path.startswith(root+'hadith-bank-reader-data/') or not re.fullmatch(r'[A-Za-z0-9_./-]+',path[1:]) or '..' in path.split('/') or path in seen or not re.fullmatch(r'[0-9a-f]{64}',digest) or not isinstance(size,int) or size<=0:raise ValueError('unsafe manifest row')
 seen.add(path);targets.append({'path':path,'bytes':size,'sha256':digest})
targets.append({'path':root+'release-manifest.json','bytes':len(raw),'sha256':mh})
dest=pathlib.Path(a.receipts);dest.mkdir(parents=True,exist_ok=True)
def check_tag():
 ref='refs/tags/'+a.tag
 r=subprocess.run(['git','ls-remote','--refs','https://github.com/blaghtayt-alt/Hadith-Bank-data.git',ref],capture_output=True,text=True,timeout=45)
 if r.returncode:raise RuntimeError('could not verify retention tag')
 lines=r.stdout.strip().splitlines()
 if len(lines)!=1 or lines[0].split()!=[a.commit,ref]:raise RuntimeError('retention tag missing or points elsewhere')
def write(name,data):
 path=dest/name
 if path.exists():raise RuntimeError('receipt already exists: '+str(path))
 path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
def verify(pair):
 i,x=pair;prefix='/Hadith-Bank-data/'
 url='https://raw.githubusercontent.com/blaghtayt-alt/Hadith-Bank-data/'+a.commit+'/objects/'+x['sha256']
 for attempt in range(3):
  try:
   req=urllib.request.Request(url,headers={'Origin':'https://blaghtayt-alt.github.io','Accept-Encoding':'identity','User-Agent':'Hadith-Bank-retained-release-gate'})
   with urllib.request.build_opener(NoRedirect).open(req,timeout=40) as r:
    if r.status!=200 or r.geturl()!=url or r.headers.get('Content-Encoding') or r.headers.get('Access-Control-Allow-Origin') not in ('*','https://blaghtayt-alt.github.io'):raise RuntimeError('status, redirect, encoding or CORS mismatch')
    h=hashlib.sha256();n=0
    while b:=r.read(262144):h.update(b);n+=len(b)
   if n!=x['bytes'] or h.hexdigest()!=x['sha256']:raise RuntimeError('body size or SHA-256 mismatch')
   return {'index':i,'url':url,'bytes':n,'sha256':h.hexdigest(),'status':'PASS'}
  except Exception as e:
   error=type(e).__name__+': '+str(e)[:140]
   if attempt<2:time.sleep(0.5*(attempt+1))
 return {'index':i,'url':url,'status':'FAIL','error':error}
if a.mode=='chunk':
 if a.start is None or a.end is None or not (0<=a.start<a.end<=len(targets)):raise ValueError('invalid chunk range')
 meta={'mode':'chunk','commit':a.commit,'tag':a.tag,'manifestSHA256':mh,'range':[a.start,a.end],'checkedAtUTC':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 try:check_tag()
 except Exception as e:
  meta.update(status='FAIL',error=str(e));write('CHUNK-%04d-%04d.json'%(a.start,a.end),meta);print(json.dumps(meta));sys.exit(1)
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:results=list(ex.map(verify,enumerate(targets[a.start:a.end],a.start)))
 failed=[x for x in results if x['status']!='PASS'];meta.update(status='PASS' if not failed else 'FAIL',verified=len(results)-len(failed),failed=len(failed),results=results)
 write('CHUNK-%04d-%04d.json'%(a.start,a.end),meta);print(json.dumps({k:v for k,v in meta.items() if k!='results'}))
 if failed:print(json.dumps(failed[:3]));sys.exit(1)
else:
 check_tag();seenIndexes=set();parts=[]
 for file in sorted(dest.glob('CHUNK-*.json')):
  b=file.read_bytes();chunk=json.loads(b)
  if chunk.get('status')!='PASS' or chunk.get('commit')!=a.commit or chunk.get('tag')!=a.tag or chunk.get('manifestSHA256')!=mh:raise RuntimeError('failed or mismatched chunk '+file.name)
  at=datetime.datetime.fromisoformat(chunk['checkedAtUTC'])
  if datetime.datetime.now(datetime.timezone.utc)-at>datetime.timedelta(hours=2):raise RuntimeError('chunk is too old')
  for r in chunk['results']:
   i=r['index']
   if i in seenIndexes or i<0 or i>=len(targets):raise RuntimeError('duplicate or invalid row')
   x=targets[i]
   expected='https://raw.githubusercontent.com/blaghtayt-alt/Hadith-Bank-data/'+a.commit+'/objects/'+x['sha256']
   if r['status']!='PASS' or r['url']!=expected or r['bytes']!=x['bytes'] or r['sha256']!=x['sha256']:raise RuntimeError('row receipt mismatch')
   seenIndexes.add(i)
  parts.append({'file':file.name,'sha256':hashlib.sha256(b).hexdigest()})
 if seenIndexes!=set(range(len(targets))):raise RuntimeError('not every required fallback was verified')
 report={'status':'PASS_ALL_COMMIT_PINNED_FALLBACKS','commit':a.commit,'tag':a.tag,'manifestSHA256':mh,'verifiedObjects':len(targets),'includesReleaseManifest':True,'retentionTagRechecked':True,'checkedAtUTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'parts':parts}
 if not a.verify_only:write('FALLBACK-PRE-SWITCH-GATE.json',report)
 print(json.dumps(report))
