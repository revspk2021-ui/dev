"""Create an explicitly pre-approved demonstration. Never makes paid requests."""
from fastapi.testclient import TestClient
from . import main as m, providers

def generate():
    if providers.MODE!='mock': raise SystemExit('Sample generation is permitted only in mock mode.')
    m.init();c=TestClient(m.app)
    for p in c.get('/api/projects').json():
        if p['topic']=='DEMO · A calmer approach to saving':
            print('Demo already exists:',p['id']);return
    def post(path,body=None):
        r=c.post(path,json=body or {});r.raise_for_status();return r.json()
    p=post('/api/projects',{'topic':'DEMO · A calmer approach to saving','duration':15,'research':'This is a pre-approved mock demonstration, not financial advice. Create a new project for your own approval workflow.'})
    base='/api/projects/'+p['id']
    post(base+'/script/generate')
    while m.process_next(): pass
    p=c.get(base).json();doc=p['script'];doc['hook']='A calmer way to start saving.'
    doc['scenes']=[{'narration':'A calmer way to start saving. Start with your own goals.','visual':'Liam beside a simple savings jar.','overlay':'Small steps. Your pace.'},{'narration':'Check original sources before making decisions. This mock demonstration is not personal financial advice.','visual':'Liam reviewing source notes at his desk.','overlay':'Check the sources'}]
    p=c.put(base+'/script',json={'revision':p['script_rev'],'script':doc}).json()
    post(base+'/script/approve',{'revision':p['script_rev']})
    post(base+'/images/generate')
    while m.process_next():pass
    p=c.get(base).json()
    post(base+'/images/approve',{'revision':p['script_rev'],'approvals':[{'index':i,'asset_id':s['current']['id']} for i,s in enumerate(p['images'])]})
    post(base+'/audio/generate')
    while m.process_next():pass
    p=c.get(base).json()
    if p['state']!='Ready': raise SystemExit('Demo failed: '+str(p['jobs']))
    print('Mock sample ready:',p['id'],p['video']['path'])

def main():
    import fcntl
    with (m.DATA/'instance.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('Stop the studio before creating the sample.')
        generate()

if __name__=='__main__': main()
