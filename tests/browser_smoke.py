from playwright.sync_api import sync_playwright
import json, time
from pathlib import Path
from urllib.request import urlopen

# Refuse to incur provider charges even if a live server happens to be running.
with urlopen('http://127.0.0.1:8000/api/config') as response:
 assert json.load(response)['mode']=='mock', 'Browser smoke tests require mock mode.'
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1050})
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://127.0.0.1:8000');page.get_by_role('heading',name='Your next good idea.').wait_for()
 page.screenshot(path='/tmp/studio-home.png',full_page=True)
 page.locator('#new-project').click();page.locator('[name=topic]').fill('BROWSER TEST · Everyday investing')
 page.locator('[name=research]').fill('A mock demonstration only; no current financial claims.')
 page.get_by_role('button',name='Create project →').click()
 page.get_by_role('button',name='Generate script →').click();page.locator('#script-form').wait_for(timeout=20000)
 for i in range(3):page.locator(f'[name=narration-{i}]').fill(f'Scene {i+1}. Take your time.')
 page.get_by_role('button',name='Save edits',exact=True).click()
 page.get_by_role('button',name='Approve this script ✓').click()
 page.get_by_role('button',name='Generate missing images').click()
 page.locator('.scene-card img').nth(2).wait_for(timeout=20000)
 page.screenshot(path='/tmp/studio-images.png',full_page=True)
 page.get_by_role('button',name='Approve all images ✓').click()
 page.get_by_role('button',name='03 · Voice & video').click()
 page.locator('#settings-form [name=voice_id]').fill('my-browser-test-voice')
 page.get_by_role('button',name='Save project settings').click()
 page.get_by_role('button',name='Generate narration →').click()
 page.locator('video').wait_for(timeout=90000)
 page.wait_for_function('document.querySelector("video").readyState >= 2',timeout=20000)
 video=page.locator('video');duration=video.evaluate('(v)=>v.duration');assert duration>0
 video.evaluate('(v)=>v.play()');page.wait_for_timeout(1200);assert video.evaluate('(v)=>v.currentTime')>0
 page.get_by_role('link',name='Download MP4',exact=True).wait_for()
 page.screenshot(path='/tmp/studio-finished.png',full_page=True)
 assert not errors,errors
 page.reload();page.get_by_role('heading',name='Your next good idea.').wait_for()
 page.set_viewport_size({'width':390,'height':844});page.screenshot(path='/tmp/studio-mobile.png',full_page=True)
 print(json.dumps({'browser':'Chromium','console_errors':errors,'playable_video_duration':duration,'workflow':'create → script edit → approval → images → approval → chosen voice → rendered video → playback; reload persisted'},indent=2))
 browser.close()
