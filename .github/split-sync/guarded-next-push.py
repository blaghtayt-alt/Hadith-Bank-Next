#!/usr/bin/env python3
"""Require verified retained objects and explicit corrected-Original confirmation before a Next push."""
import argparse,datetime,hashlib,json,os,pathlib,re,subprocess,sys,urllib.request
ap=argparse.ArgumentParser()
for key in ['candidate','expected-head','expected-remote-head','source-commit','manifest','manifest-sha256','fallback-commit','tag','fallback-receipts','confirmation']:ap.add_argument('--'+key,required=True)
ap.add_argument('--records',type=int,required=True);ap.add_argument('--publish',action='store_true')
a=ap.parse_args()
for x in (a.expected_head,a.expected_remote_head,a.source_commit,a.fallback_commit):
 if not re.fullmatch(r'[0-9a-f]{40}',x) or x=='0'*40:raise ValueError('invalid commit')
if a.tag!='retain-'+a.fallback_commit:raise ValueError('invalid retention tag')
confirm=json.loads(pathlib.Path(a.confirmation).read_text(encoding='utf-8-sig'))
if confirm.get('confirmed_corrected_original_live') is not True or confirm.get('sourceCommit')!=a.source_commit or confirm.get('records')!=a.records:raise RuntimeError('corrected Original confirmation missing or mismatched')
manifest=pathlib.Path(a.manifest).read_bytes()
if hashlib.sha256(manifest).hexdigest()!=a.manifest_sha256:raise RuntimeError('manifest checksum mismatch')
m=json.loads(manifest)
if m.get('source_commit')!=a.source_commit:raise RuntimeError('manifest source differs from confirmed Original')
verifier=pathlib.Path(__file__).with_name('verify-retained-objects.py')
cmd=[sys.executable,str(verifier),'--mode','gate','--verify-only','--manifest',a.manifest,'--manifest-sha256',a.manifest_sha256,'--commit',a.fallback_commit,'--tag',a.tag,'--receipts',a.fallback_receipts]
gate=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=90)
if gate.returncode:raise RuntimeError('retained-object gate failed or is incomplete; no publication')
proof=json.loads(gate.stdout.strip().splitlines()[-1])
if proof.get('status')!='PASS_ALL_COMMIT_PINNED_FALLBACKS' or proof.get('verifiedObjects')!=len(m['rows'])+1:raise RuntimeError('retained-object gate result mismatch')
env=os.environ.copy();env.update(GCM_INTERACTIVE='Never',GIT_TERMINAL_PROMPT='0')
def git(*args,bytes_out=False):
 r=subprocess.run(['git','-c','safe.directory='+a.candidate.replace('\\','/'),'-C',a.candidate,*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=90)
 if r.returncode:raise RuntimeError('git precondition failed: '+args[0])
 return r.stdout if bytes_out else r.stdout.decode('utf-8').strip()
if git('rev-parse','HEAD')!=a.expected_head or git('status','--porcelain'):raise RuntimeError('candidate commit or worktree differs')
i=git('show','HEAD:index.html',bytes_out=True);j=git('show','HEAD:hadith-bank-reader.html',bytes_out=True)
if i!=j:raise RuntimeError('reader aliases differ')
for needle in [("RAW_COMMIT='"+a.fallback_commit+"'").encode(),a.manifest_sha256.encode(),b'https://raw.githubusercontent.com',b"'/objects/'",b'HadithSplitResponseMatches']:
 if needle not in i:raise RuntimeError('candidate does not pin verified fallback')
build=json.loads(git('show','HEAD:build-info.json',bytes_out=True))
if build.get('source_commit')!=a.source_commit or build.get('record_count')!=a.records or build.get('search_sha256')!=m.get('source_records_sha256'):raise RuntimeError('candidate build identity differs')
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
url='https://blaghtayt-alt.github.io/Hadith-Bank/build-info.json'
req=urllib.request.Request(url,headers={'Accept-Encoding':'identity','User-Agent':'Hadith-Bank-guarded-sync'})
with urllib.request.build_opener(NoRedirect).open(req,timeout=30) as r:
 if r.status!=200 or r.geturl()!=url:raise RuntimeError('Original build-info redirected')
 live=json.load(r)
if live.get('source_commit')!=a.source_commit or live.get('record_count')!=a.records or live.get('search_sha256')!=m.get('source_records_sha256'):raise RuntimeError('live Original identity differs')
remote=subprocess.run(['git','ls-remote','--refs','https://github.com/blaghtayt-alt/Hadith-Bank-Next.git','refs/heads/main'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,text=True,timeout=45)
if remote.returncode or remote.stdout.strip().split()!=[a.expected_remote_head,'refs/heads/main']:raise RuntimeError('remote Next head changed')
git('merge-base','--is-ancestor',a.expected_remote_head,a.expected_head)
result={'status':'READY_NOT_PUBLISHED','sourceCommit':a.source_commit,'records':a.records,'candidateCommit':a.expected_head,'previousNextCommit':a.expected_remote_head,'manifestSHA256':a.manifest_sha256,'fallbackCommit':a.fallback_commit,'retentionTag':a.tag,'verifiedFallbackObjects':proof['verifiedObjects'],'checkedAtUTC':datetime.datetime.now(datetime.timezone.utc).isoformat()}
if a.publish:
 r=subprocess.run(['git','-c','safe.directory='+a.candidate.replace('\\','/'),'-C',a.candidate,'push','https://github.com/blaghtayt-alt/Hadith-Bank-Next.git',a.expected_head+':refs/heads/main'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=300)
 if r.returncode:raise RuntimeError('guarded push failed; check remote before retry')
 after=subprocess.run(['git','ls-remote','--refs','https://github.com/blaghtayt-alt/Hadith-Bank-Next.git','refs/heads/main'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,text=True,timeout=45)
 if after.returncode or after.stdout.strip().split()!=[a.expected_head,'refs/heads/main']:raise RuntimeError('push returned but remote readback not confirmed')
 result['status']='PUSHED_REMOTE_HEAD_VERIFIED'
print(json.dumps(result))
