import copy
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from . import providers, render as renderer

ROOT=Path(__file__).resolve().parent.parent
DATA=Path(os.getenv('DATA_DIR',str(ROOT/'data'))).resolve();DATA.mkdir(parents=True,exist_ok=True)
ASSETS=DATA/'assets';ASSETS.mkdir(exist_ok=True)
LOCK=threading.RLock();STOP=threading.Event()
DEFAULTS={'voice':{'voice_id':'','stability':0.5,'similarity_boost':0.75,'style':0.0,'use_speaker_boost':True,'speed':1.0},'render':{'captions':True,'motion':'static','transition':'cut','review_audio':False},'limits':{'max_images':8,'max_retries':2},'references':[]}

def uid(): return uuid.uuid4().hex

def digest(x): return hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()

def fail(message,code=409): raise HTTPException(code,message)

@contextmanager
def db():
    with LOCK:
        c=sqlite3.connect(DATA/'studio.sqlite3');c.row_factory=sqlite3.Row
        try:
            yield c;c.commit()
        except BaseException:
            c.rollback();raise
        finally: c.close()

def init():
    with db() as c:
        c.executescript('''PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project TEXT NOT NULL, kind TEXT NOT NULL, signature TEXT NOT NULL, status TEXT NOT NULL, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, job TEXT NOT NULL, unit TEXT NOT NULL, status TEXT NOT NULL, doc TEXT NOT NULL, UNIQUE(job,unit));
''')
        c.execute('INSERT OR IGNORE INTO settings VALUES(1,?)',(json.dumps(DEFAULTS),))
        # Never replay an interrupted paid operation automatically.
        for row in c.execute("SELECT * FROM jobs WHERE status='running'").fetchall():
            j=json.loads(row['doc']);j.update(status='failed',error='Interrupted by restart. Completed steps are retained. Retry to resume; uncertain live calls require acknowledgement.',progress='Interrupted');savejob(c,j)

def getp(c,pid):
    row=c.execute('SELECT doc FROM projects WHERE id=?',(pid,)).fetchone()
    if not row: fail('Project not found',404)
    return json.loads(row[0])

def savep(c,p):
    p['updated']=time.time();c.execute('INSERT OR REPLACE INTO projects VALUES(?,?)',(p['id'],json.dumps(p)))

def savejob(c,j):
    c.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?)',(j['id'],j['project'],j['kind'],j['signature'],j['status'],json.dumps(j)))

def jobs(c,pid): return [json.loads(r[0]) for r in c.execute('SELECT doc FROM jobs WHERE project=? ORDER BY rowid DESC',(pid,))]

def script_ok(p): return bool(p.get('script') and p['script_approval']==p['script_rev'])

def images_ok(p): return bool(script_ok(p) and p['images'] and all(s.get('current') and s['approval']==s['current']['id'] for s in p['images']))

def audio_sig(p): return digest([p['script_rev'],[(s.get('current') or {}).get('id') for s in p['images']],p['voice'],p['audio_nonce'],providers.MODE])

def audio_ok(p): return images_ok(p) and bool(p.get('audio') and p['audio']['signature']==audio_sig(p))

def signature(p,kind,index=None):
    if kind=='script': return digest([p['script_rev'],p['topic'],p['research'],p['sources'],p['key_points'],p['creative'],p['duration'],p['limits']['max_images'],p['script_nonce'],providers.MODE])
    if kind=='image': return digest([p['script_rev'],p['format'],p['references'],index,p['images'][index]['nonce'],providers.MODE])
    if kind=='audio': return audio_sig(p)
    if kind=='render': return digest([p['audio']['id'] if audio_ok(p) else None,p['render'],p['format'],p.get('overlays',[])])

def guard(p,kind):
    if kind=='image' and not script_ok(p): fail('Approve the current script before generating images.')
    if kind in ('audio','render') and not images_ok(p): fail('Approve every current scene image before narration or rendering.')
    if kind=='render' and not audio_ok(p): fail('Generate narration for the current approved assets first.')

def current(p,j):
    try:
        guard(p,j['kind']);return signature(p,j['kind'],j.get('index'))==j['signature']
    except (HTTPException,IndexError): return False

def budget_used(c,p,kind,index=None):
    relevant=[j for j in jobs(c,p['id']) if j['kind']==kind and (kind=='script' or j['snapshot']['script_rev']==p['script_rev']) and (kind!='image' or j['index']==index)]
    return sum(max(1,j['attempts']) for j in relevant if j['status']!='discarded' or j['attempts']>0)

def enqueue(c,p,kind,index=None,feedback=''):
    guard(p,kind);sig=signature(p,kind,index)
    for j in jobs(c,p['id']):
        if j['kind']==kind and j['signature']==sig and j['status']!='discarded': return j
    if kind!='render' and budget_used(c,p,kind,index)>=1+p['limits']['max_retries']: fail('Generation/retry budget reached. Review usage before raising the project retry limit.')
    j={'id':uid(),'project':p['id'],'kind':kind,'index':index,'signature':sig,'status':'queued','progress':'Queued','error':None,'attempts':0,'snapshot':copy.deepcopy(p),'feedback':feedback,'created':time.time()}
    savejob(c,j);return j

def view(c,p):
    result=copy.deepcopy(p);js=jobs(c,p['id']);valid=[j for j in js if current(p,j)]
    active=next((j for j in valid if j['status'] in ('queued','running')),None)
    failed=next((j for j in valid if j['status']=='failed'),None)
    if active:
        state={'script':'Script generating','image':'Images generating','audio':'Audio generating','render':'Video rendering'}[active['kind']]
    elif failed: state='Failed'
    elif audio_ok(p) and p.get('video') and p['video']['signature']==signature(p,'render'): state='Ready'
    elif audio_ok(p): state='Audio ready'
    elif images_ok(p): state='Images approved'
    elif script_ok(p): state='Images awaiting approval' if any(s.get('current') for s in p['images']) else 'Script approved'
    elif p.get('script'): state='Script ready'
    else: state='Draft'
    result.update(state=state,script_approved=script_ok(p),images_approved=images_ok(p),audio_current=audio_ok(p),video_current=state=='Ready',mode=providers.MODE)
    result['jobs']=[{k:v for k,v in j.items() if k!='snapshot'} for j in js]
    result['usage']=[{'job':r['job'],'unit':r['unit'],'status':r['status'],**json.loads(r['doc']).get('usage',{})} for r in c.execute('SELECT calls.* FROM calls JOIN jobs ON calls.job=jobs.id WHERE jobs.project=?',(p['id'],))]
    return result

def validate_script(doc,limit):
    if not isinstance(doc,dict) or not isinstance(doc.get('hook'),str): fail('Script needs an opening hook.',422)
    scenes=doc.get('scenes',[])
    if not isinstance(scenes,list) or not 1<=len(scenes)<=limit: fail(f'Use between 1 and {limit} scenes.',422)
    for s in scenes:
        if not isinstance(s,dict) or any(not isinstance(s.get(k),str) for k in ('narration','visual','overlay')) or not s['narration'].strip(): fail('Each scene needs narration, a visual description and overlay text.',422)
        if len(s['narration'])>12000 or len(s['overlay'])>160 or len(s['visual'])>4000: fail('Scene text is too long (narration 12,000, overlay 160, visual 4,000 characters).',422)
    if not isinstance(doc.get('fact_check'),dict): fail('Include the separate fact-check report.',422)
    return doc

def apply_script(p,doc):
    if p.get('script'): p['history'].append({'kind':'script','revision':p['script_rev'],'script':p['script'],'images':p['images'],'audio':p.get('audio'),'video':p.get('video')})
    p['script_rev']+=1;p['script']=doc;p['script_approval']=None;p['overlays']=[s['overlay'] for s in doc['scenes']]
    p['images']=[{'current':None,'approval':None,'versions':[],'nonce':0} for _ in doc['scenes']]
    p['audio']=None;p['video']=None

def public_asset(path,**extra): return {'id':path.stem,'path':str(path),'url':'/assets/'+path.name,**extra}

def checkpoint(jid,progress):
    with db() as c:
        j=json.loads(c.execute('SELECT doc FROM jobs WHERE id=?',(jid,)).fetchone()[0]);j['progress']=progress;savejob(c,j)

def call(j,unit,fn):
    with db() as c:
        row=c.execute('SELECT * FROM calls WHERE job=? AND unit=?',(j['id'],unit)).fetchone()
        if row and row['status']=='done': return json.loads(row['doc'])['result']
        if row and row['status']=='pending' and providers.MODE=='live' and not j.get('acknowledge_uncertain'): raise RuntimeError('A live provider request may already have been charged. Review provider usage, then acknowledge a potentially duplicate charge to retry.')
        c.execute('INSERT OR REPLACE INTO calls VALUES(?,?,?,?,?)',(row['id'] if row else uid(),j['id'],unit,'pending','{}'))
    result=fn()
    usage=result.pop('_usage',{})
    with db() as c: c.execute("UPDATE calls SET status='done',doc=? WHERE job=? AND unit=?",(json.dumps({'result':result,'usage':{'mode':providers.MODE,**usage}}),j['id'],unit))
    return result

def split_text(text,limit):
    # Split on whitespace; preserve punctuation and every word, never truncate.
    words=text.split();parts=[];chunk=''
    for word in words:
        if len(word)>limit: raise RuntimeError('A narration word exceeds the provider text limit. Edit the narration.')
        if len(chunk)+len(word)+1>limit:
            parts.append(chunk);chunk=''
        chunk=(chunk+' '+word).strip()
    if chunk: parts.append(chunk)
    return parts

def execute(j):
    p=j['snapshot'];kind=j['kind'];work=ASSETS/j['id'];work.mkdir(exist_ok=True)
    if providers.MODE=='live' and kind!='render':
        required={'script':('OPENAI_API_KEY','OPENAI_TEXT_MODEL'),'image':('OPENAI_API_KEY','OPENAI_IMAGE_MODEL'),'audio':('ELEVENLABS_API_KEY','ELEVENLABS_MODEL_ID')}
        for name in required[kind]: providers.config(name)
    if kind=='script':
        def generate():
            result=providers.script(p,j['feedback']);doc,usage=result if isinstance(result,tuple) else (result,{})
            validate_script(doc,p['limits']['max_images']);return {'doc':doc,'_usage':usage}
        result=call(j,'script',generate)
    elif kind=='image':
        i=j['index'];out=ASSETS/(uid()+'.png')
        def generate():
            usage=providers.image(p,p['script']['scenes'][i],[r['path'] for r in p['references']],out,j['feedback'])
            return {'asset':public_asset(out,mode=providers.MODE),'_usage':usage}
        result=call(j,'image',generate)
    elif kind=='audio':
        manifest=[];limit=min(2000,max(50,int(os.getenv('ELEVENLABS_TEXT_LIMIT','2000'))))
        for i,scene in enumerate(p['script']['scenes']):
            chunks=[]
            parts=split_text(scene['narration'],limit)
            for k,text in enumerate(parts):
                checkpoint(j['id'],f'Narration: scene {i+1}, part {k+1}')
                before=' '.join([s['narration'] for s in p['script']['scenes'][:i]]+parts[:k])[-800:]
                after=' '.join(parts[k+1:]+[s['narration'] for s in p['script']['scenes'][i+1:]])[:800]
                def generate(text=text,before=before,after=after):
                    out=ASSETS/(uid()+('.wav' if providers.MODE=='mock' else '.mp3'))
                    meta=providers.audio(text,{**p['voice'],'_previous_text':before,'_next_text':after},out)
                    return {'path':str(out),'text':text,'duration':renderer.duration(out),**meta,'_usage':{'characters':len(text),'voice_id':p['voice']['voice_id']}}
                chunks.append(call(j,f'audio-{i}-{k}',generate))
            sceneout=work/f'scene-{i}.wav';renderer.concat_audio([x['path'] for x in chunks],sceneout)
            manifest.append({'path':str(sceneout),'duration':renderer.duration(sceneout),'chunks':chunks})
        out=ASSETS/(uid()+'.wav');renderer.concat_audio([x['path'] for x in manifest],out)
        result={'asset':public_asset(out,signature=j['signature'],manifest=manifest,mode=providers.MODE,voice_id=p['voice']['voice_id'])}
    else:
        out=ASSETS/(uid()+'.mp4')
        meta=renderer.render(p,p['audio']['manifest'],work,out,lambda s:checkpoint(j['id'],s))
        result={'asset':public_asset(out,signature=j['signature'],mode=providers.MODE,**meta)}
    with db() as c:
        latest=getp(c,j['project']);record=json.loads(c.execute('SELECT doc FROM jobs WHERE id=?',(j['id'],)).fetchone()[0])
        if not current(latest,j):
            latest['history'].append({'kind':kind,'outdated_result':result});record.update(status='discarded',progress='Preserved as outdated; newer project version exists.')
        else:
            if kind=='script': apply_script(latest,result['doc'])
            elif kind=='image':
                slot=latest['images'][j['index']];slot['current']=result['asset'];slot['versions'].append(result['asset']);slot['approval']=None
            elif kind=='audio':
                if latest.get('audio'): latest['history'].append({'kind':'audio',**latest['audio']})
                latest['audio']=result['asset']
            else:
                if latest.get('video'): latest['history'].append({'kind':'video',**latest['video']})
                latest['video']=result['asset']
            record.update(status='done',progress='Complete',error=None)
        savep(c,latest);savejob(c,record)
        if kind=='audio' and record['status']=='done' and not latest['render']['review_audio']: enqueue(c,latest,'render')

def process_next():
    with db() as c:
        row=c.execute("SELECT doc FROM jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
        if not row: return False
        j=json.loads(row[0]);p=getp(c,j['project'])
        if not current(p,j):
            j.update(status='discarded',progress='Inputs changed; no provider request was made.');savejob(c,j);return True
        j.update(status='running',attempts=j['attempts']+1,progress='Starting');savejob(c,j)
    try: execute(j)
    except Exception as e:
        msg=e.detail if isinstance(e,HTTPException) else str(e) if isinstance(e,RuntimeError) else f'{type(e).__name__}: operation failed. Check configuration and retry.'
        with db() as c:
            j=json.loads(c.execute('SELECT doc FROM jobs WHERE id=?',(j['id'],)).fetchone()[0]);j.update(status='failed',error=msg,progress='Needs attention');savejob(c,j)
    return True

def worker():
    while not STOP.wait(.15): process_next()

@asynccontextmanager
async def lifespan(app):
    import fcntl
    instance_lock=(DATA/'instance.lock').open('a')
    try: fcntl.flock(instance_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        instance_lock.close();raise RuntimeError('This data directory is already in use. Run a single app instance and worker.')
    try:
        init();STOP.clear();thread=threading.Thread(target=worker,daemon=True);thread.start()
        yield
    finally:
        STOP.set()
        if 'thread' in locals(): thread.join()
        instance_lock.close()

app=FastAPI(title='The Lazy Aussie Investor Studio',lifespan=lifespan)

@app.middleware('http')
async def local_only(request:Request,call_next):
    # Local single-user tool: disallow DNS rebinding and cross-origin mutation.
    host=request.url.hostname
    if host not in ('127.0.0.1','localhost','::1','testserver'): return __import__('starlette.responses',fromlist=['JSONResponse']).JSONResponse({'detail':'Use this app through localhost.'},status_code=403)
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD') and origin and urlparse(origin).netloc!=request.headers.get('host'): return __import__('starlette.responses',fromlist=['JSONResponse']).JSONResponse({'detail':'Cross-origin requests are blocked.'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' blob:; media-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    return response

@app.get('/api/config')
def configuration():
    return {'mode':providers.MODE,'openai_key_present':bool(os.getenv('LAZY_OPENAI_KEY') or os.getenv('OPENAI_API_KEY')),'elevenlabs_key_present':bool(os.getenv('ELEVENLABS_API_KEY')),'text_model':os.getenv('OPENAI_TEXT_MODEL',''),'image_model':os.getenv('OPENAI_IMAGE_MODEL',''),'elevenlabs_model':os.getenv('ELEVENLABS_MODEL_ID',''),'ffmpeg':__import__('shutil').which('ffmpeg') is not None}

@app.get('/api/preferences')
def preferences():
    with db() as c: return json.loads(c.execute('SELECT doc FROM settings WHERE id=1').fetchone()[0])

def clean_settings(body,base):
    result=copy.deepcopy(base)
    for section in ('voice','render','limits'):
        if section in body:
            if not isinstance(body[section],dict) or set(body[section])-set(DEFAULTS[section]): fail('Unknown settings.',422)
            result[section].update(body[section])
    v=result['voice'];r=result['render'];lim=result['limits']
    for k in ('stability','similarity_boost','style'):
        if isinstance(v[k],bool) or not isinstance(v[k],(int,float)) or not 0<=v[k]<=1: fail(f'{k} must be between 0 and 1.',422)
    if not isinstance(v['voice_id'],str) or len(v['voice_id'])>100 or (v['voice_id'] and not re.fullmatch('[A-Za-z0-9_-]+',v['voice_id'])): fail('Invalid voice ID.',422)
    if not isinstance(v['speed'],(float,int)) or not .7<=v['speed']<=1.2: fail('Voice speed must be 0.7–1.2.',422)
    if type(v['use_speaker_boost']) is not bool or type(r['captions']) is not bool or type(r['review_audio']) is not bool: fail('Invalid toggle setting.',422)
    if r['motion'] not in ('static','gentle') or r['transition']!='cut': fail('Choose static or gentle motion and simple cuts.',422)
    if type(lim['max_images']) is not int or not 1<=lim['max_images']<=20 or type(lim['max_retries']) is not int or not 0<=lim['max_retries']<=5: fail('Image limit 1–20; retry limit 0–5.',422)
    return result

@app.put('/api/preferences')
def save_preferences(body:dict):
    with db() as c:
        old=json.loads(c.execute('SELECT doc FROM settings WHERE id=1').fetchone()[0]);s=clean_settings(body,old);c.execute('UPDATE settings SET doc=? WHERE id=1',(json.dumps(s),));return s

@app.post('/api/projects')
def create(body:dict):
    topic=body.get('topic','').strip() if isinstance(body.get('topic',''),str) else ''
    if not topic or len(topic)>300: fail('Enter a topic (up to 300 characters).',422)
    fmt=body.get('format','vertical');seconds=body.get('duration',45)
    if fmt not in ('vertical','landscape') or type(seconds) not in (int,float) or not 5<=seconds<=1800: fail('Choose a valid format and target duration (5–1800 seconds).',422)
    sources=body.get('sources',[])
    if not isinstance(sources,list) or len(sources)>50 or any(not isinstance(s,str) or len(s)>2000 or urlparse(s).scheme not in ('http','https') for s in sources): fail('Sources must be HTTP(S) links.',422)
    fields={k:body.get(k,'') for k in ('research','key_points','creative')}
    if any(not isinstance(v,str) or len(v)>50000 for v in fields.values()): fail('Research and instructions must be text under 50,000 characters.',422)
    with db() as c:
        pref=json.loads(c.execute('SELECT doc FROM settings WHERE id=1').fetchone()[0])
        p={'id':uid(),'topic':topic,**fields,'sources':sources,'format':fmt,'duration':seconds,**pref,'script':None,'script_rev':0,'script_nonce':0,'script_approval':None,'images':[],'audio':None,'audio_nonce':0,'video':None,'history':[],'created':time.time()}
        savep(c,p);return view(c,p)

@app.get('/api/projects')
def projects():
    with db() as c: return [view(c,json.loads(r[0])) for r in c.execute('SELECT doc FROM projects ORDER BY rowid DESC').fetchall()]

@app.get('/api/projects/{pid}')
def project(pid:str):
    with db() as c: return view(c,getp(c,pid))

@app.put('/api/projects/{pid}/settings')
def settings(pid:str,body:dict):
    with db() as c:
        p=getp(c,pid);s=clean_settings(body,p)
        if p['script'] and len(p['images'])>s['limits']['max_images']: fail('Image limit cannot be lower than your existing scene count.',422)
        for section in ('voice','render','limits'): p[section]=s[section]
        savep(c,p);return view(c,p)

@app.post('/api/projects/{pid}/script/generate')
def generate_script(pid:str,body:dict):
    with db() as c:
        p=getp(c,pid)
        if p['script'] and not body.get('new_version'):
            previous=next((j for j in jobs(c,pid) if j['kind']=='script' and j['status']=='done'),None)
            if previous: return previous
        if body.get('new_version'):
            # Duplicate clicks while an identical operation is active reuse it.
            active=next((j for j in jobs(c,pid) if j['kind']=='script' and j['status'] in ('queued','running') and current(p,j)),None)
            if active: return active
            if body.get('base_revision')!=p['script_rev']: fail('The script changed. Refresh before requesting another revision.')
            if sum(1 for j in jobs(c,pid) if j['kind']=='script')>=1+p['limits']['max_retries']: fail('Script generation limit reached. Review before raising the retry limit.')
            p['script_nonce']+=1;savep(c,p)
        feedback=body.get('feedback','')
        if not isinstance(feedback,str) or len(feedback)>5000: fail('Feedback must be under 5,000 characters.',422)
        return enqueue(c,p,'script',feedback=feedback)

@app.put('/api/projects/{pid}/script')
def edit_script(pid:str,body:dict):
    with db() as c:
        p=getp(c,pid)
        if body.get('revision')!=p['script_rev']: fail('The script changed. Refresh before saving.')
        doc=validate_script(body.get('script'),p['limits']['max_images'])
        if doc!=p.get('script'): apply_script(p,doc)
        savep(c,p);return view(c,p)

@app.post('/api/projects/{pid}/script/approve')
def approve_script(pid:str,body:dict):
    with db() as c:
        p=getp(c,pid)
        if not p['script'] or body.get('revision')!=p['script_rev']: fail('Approve only the current script revision.')
        p['script_approval']=p['script_rev'];savep(c,p);return view(c,p)

@app.put('/api/projects/{pid}/overlays')
def overlays(pid:str,body:dict):
    with db() as c:
        p=getp(c,pid)
        if not p['script'] or body.get('revision')!=p['script_rev']: fail('Script changed. Refresh before editing overlays.')
        i=body.get('index');text=body.get('text')
        if type(i) is not int or not 0<=i<len(p['images']) or not isinstance(text,str) or len(text)>160: fail('Invalid scene overlay (maximum 160 characters).',422)
        p.setdefault('overlays',[s['overlay'] for s in p['script']['scenes']])[i]=text
        savep(c,p);return view(c,p)

@app.post('/api/projects/{pid}/images/generate')
def generate_images(pid:str):
    with db() as c:
        p=getp(c,pid);guard(p,'image')
        return [enqueue(c,p,'image',i) for i,s in enumerate(p['images']) if not s['current']]

def slot(p,index):
    if not 0<=index<len(p['images']): fail('Scene not found',404)
    return p['images'][index]

@app.post('/api/projects/{pid}/images/{index}/regenerate')
def regenerate(pid:str,index:int,body:dict):
    with db() as c:
        p=getp(c,pid);guard(p,'image');s=slot(p,index)
        active=next((j for j in jobs(c,pid) if j['kind']=='image' and j['index']==index and j['status'] in ('queued','running') and current(p,j)),None)
        if active: return active
        if body.get('asset_id')!=(s.get('current') or {}).get('id'): fail('Image changed. Refresh before regenerating.')
        feedback=body.get('feedback','')
        if not isinstance(feedback,str) or len(feedback)>2000: fail('Feedback must be under 2,000 characters.',422)
        used=sum(1 for j in jobs(c,pid) if j['kind']=='image' and j.get('index')==index and j['snapshot']['script_rev']==p['script_rev'])
        if used>=1+p['limits']['max_retries']: fail('Scene generation/retry limit reached. Raise the project retry limit deliberately to continue.')
        s['nonce']+=1;s['current']=None;s['approval']=None;savep(c,p);return enqueue(c,p,'image',index,feedback)

@app.post('/api/projects/{pid}/images/approve')
def approve_images(pid:str,body:dict):
    with db() as c:
        p=getp(c,pid);guard(p,'image')
        approvals=body.get('approvals',[])
        if not isinstance(approvals,list) or not approvals: fail('Supply the exact images to approve.',422)
        for approval in approvals:
            if not isinstance(approval,dict) or type(approval.get('index')) is not int: fail('Invalid image approval.',422)
            s=slot(p,approval.get('index',-1))
            if not s['current'] or approval.get('asset_id')!=s['current']['id'] or body.get('revision')!=p['script_rev']: fail('Image or script changed. Review the current image.')
            s['approval']=s['current']['id']
        savep(c,p);return view(c,p)

async def uploaded(file):
    content=await file.read(12*1024*1024+1)
    if len(content)>12*1024*1024: fail('Image limit is 12 MB.',413)
    try:
        with Image.open(io.BytesIO(content)) as im:
            if im.width*im.height>25000000: fail('Image exceeds 25 megapixels.',413)
            im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((2560,2560));out=ASSETS/(uid()+'.png');im.save(out)
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError): fail('Upload a valid PNG, JPEG or WebP image.',422)
    return public_asset(out,mode='upload')

@app.post('/api/projects/{pid}/images/{index}/upload')
async def replace_image(pid:str,index:int,file:UploadFile=File(...),revision:int=0,asset_id:str=''):
    asset=await uploaded(file)
    with db() as c:
        p=getp(c,pid);guard(p,'image');s=slot(p,index)
        if revision!=p['script_rev'] or asset_id!=((s.get('current') or {}).get('id') or ''): fail('Project changed. Refresh before replacing the image.')
        s['nonce']+=1;s['current']=asset;s['versions'].append(asset);s['approval']=None;savep(c,p);return view(c,p)

@app.post('/api/projects/{pid}/references/{kind}')
async def add_reference(pid:str,kind:str,file:UploadFile=File(...)):
    if kind not in ('host','style'): fail('Choose host or style reference.',422)
    asset=await uploaded(file);asset['kind']=kind
    with db() as c:
        p=getp(c,pid)
        if len(p['references'])>=8: fail('Use at most eight reference images.',422)
        p['references'].append(asset)
        # New references affect future requests; previously approved images must be reviewed again.
        for s in p['images']: s['approval']=None
        savep(c,p);return view(c,p)

@app.post('/api/projects/{pid}/references/save-defaults')
def reference_defaults(pid:str):
    with db() as c:
        p=getp(c,pid);prefs=json.loads(c.execute('SELECT doc FROM settings WHERE id=1').fetchone()[0]);prefs['references']=p['references'];c.execute('UPDATE settings SET doc=? WHERE id=1',(json.dumps(prefs),));return {'saved':True}

@app.post('/api/projects/{pid}/audio/generate')
def generate_audio(pid:str,body:dict):
    with db() as c:
        p=getp(c,pid);guard(p,'audio')
        if providers.MODE=='live' and not p['voice']['voice_id']: fail('Set your ElevenLabs voice ID first.',422)
        if body.get('regenerate'):
            active=next((j for j in jobs(c,pid) if j['kind']=='audio' and j['status'] in ('queued','running') and current(p,j)),None)
            if active: return active
            if body.get('asset_id')!=(p.get('audio') or {}).get('id'): fail('Audio changed. Refresh before regenerating.')
            used=sum(1 for j in jobs(c,pid) if j['kind']=='audio' and j['snapshot']['script_rev']==p['script_rev'])
            if used>=1+p['limits']['max_retries']: fail('Audio regeneration limit reached.')
            p['audio_nonce']+=1;savep(c,p)
        return enqueue(c,p,'audio')

@app.post('/api/projects/{pid}/render')
def render_video(pid:str):
    with db() as c: return enqueue(c,getp(c,pid),'render')

@app.post('/api/jobs/{jid}/retry')
def retry(jid:str,body:dict):
    with db() as c:
        row=c.execute('SELECT doc FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row: fail('Job not found',404)
        j=json.loads(row[0]);p=getp(c,j['project'])
        if j['status'] in ('queued','running','done'): return j
        if not current(p,j): fail('Inputs changed. Start a new operation using the current approvals.')
        if (j['attempts'] if j['kind']=='render' else budget_used(c,p,j['kind'],j.get('index')))>=1+p['limits']['max_retries']: fail('Project retry limit reached. Review configuration before raising it.')
        uncertain=c.execute("SELECT 1 FROM calls WHERE job=? AND status='pending'",(jid,)).fetchone() is not None and providers.MODE=='live'
        if uncertain and body.get('acknowledge_uncertain') is not True: fail('Provider outcome is uncertain. Check usage first; retry may cause another charge.')
        j.update(status='queued',error=None,progress='Retry queued; completed steps will be reused',acknowledge_uncertain=bool(body.get('acknowledge_uncertain')));savejob(c,j);return j

@app.get('/assets/{name}')
def asset(name:str):
    if not re.fullmatch(r'[a-f0-9]{32}\.(png|wav|mp3|mp4)',name): fail('Asset not found',404)
    path=ASSETS/name
    if not path.is_file(): fail('Asset not found',404)
    return FileResponse(path,filename=name if name.endswith('.mp4') else None,content_disposition_type='inline')

app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
@app.get('/')
def index(): return FileResponse(ROOT/'static/index.html')
