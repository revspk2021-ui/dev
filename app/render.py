"""Local FFmpeg rendering. Scene boundaries come from actual scene audio durations."""
import json
import math
import subprocess
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
from .providers import font


def run(args,cwd=None):
    p=subprocess.run(args,capture_output=True,text=True,cwd=cwd)
    if p.returncode:
        raise RuntimeError('FFmpeg failed: '+p.stderr[-1600:])
    return p.stdout

def duration(path):
    result=run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)])
    return float(json.loads(result)['format']['duration'])

def concat_entry(path):
    return "file '"+str(Path(path).resolve()).replace("'","'\\''")+"'"

def concat_audio(paths,out):
    # Filenames are server-created UUIDs and never user-controlled paths.
    listing=out.with_suffix('.txt');listing.write_text('\n'.join(concat_entry(x) for x in paths))
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(listing),'-ar','44100','-ac','1','-c:a','pcm_s16le',str(out)])

def ass_time(s):
    t=int(round(s*100));return f'{t//360000}:{t//6000%60:02}:{t//100%60:02}.{t%100:02}'

def safe_text(text):
    return text.replace('\\','').replace('{','').replace('}','').replace('\r',' ').replace('\n',' ')

def captions(manifest,w,h,out):
    out.write_text(f'''[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{44 if w==1080 else 40},&H00FFFFFF,&H00FFFFFF,&H00251F17,&H80251F17,1,0,0,0,100,100,0,0,3,2,0,2,{int(w*.12)},{int(w*.18)},{int(h*.20)},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
''')
    lines=[]; offset=0
    for scene in manifest:
        for chunk in scene['chunks']:
            align=chunk.get('alignment');text=chunk['text'];dur=chunk['duration']
            if align and len(align.get('characters',[]))==len(align.get('character_start_times_seconds',[])) and align.get('characters'):
                chars=align['characters'];starts=align['character_start_times_seconds'];ends=align.get('character_end_times_seconds',starts)
                begin=0
                for i in range(len(chars)):
                    if (i-begin>=38 and chars[i].isspace()) or i==len(chars)-1:
                        caption=safe_text(''.join(chars[begin:i+1])).strip()
                        if caption: lines.append(f'Dialogue: 0,{ass_time(offset+starts[begin])},{ass_time(offset+min(dur,ends[i]))},Default,,0,0,0,,{caption}')
                        begin=i+1
            else:
                words=text.split();groups=[words[i:i+7] for i in range(0,len(words),7)];pos=0
                for group in groups:
                    start=dur*pos/max(1,len(words));pos+=len(group);end=dur*pos/max(1,len(words))
                    lines.append(f'Dialogue: 0,{ass_time(offset+start)},{ass_time(offset+end)},Default,,0,0,0,,{safe_text(" ".join(group))}')
            offset+=dur
    with out.open('a') as f: f.write('\n'.join(lines)+'\n')

def render(p, manifest, root, out, progress=lambda x:None):
    w,h=(1080,1920) if p['format']=='vertical' else (1920,1080)
    all_audio=root/'narration.wav'
    concat_audio([Path(s['path']) for s in manifest],all_audio)
    clips=[];elapsed=0;frames_total=0
    for i,(scene,sound) in enumerate(zip(p['script']['scenes'],manifest)):
        progress(f'Rendering scene {i+1} of {len(manifest)}')
        image=Path(p['images'][i]['current']['path'])
        with Image.open(image) as im: base=ImageOps.fit(im.convert('RGB'),(w,h))
        basepath=root/f'base-{i}.png';base.save(basepath)
        overlay=Image.new('RGBA',(w,h));d=ImageDraw.Draw(overlay)
        text=(p.get('overlays') or [s.get('overlay','') for s in p['script']['scenes']])[i];size=52 if w==1080 else 48
        wrapped=textwrap.wrap(text,width=27 if w==1080 else 55)
        y=int(h*.125)
        if wrapped:
            d.rounded_rectangle((int(w*.10),y-22,int(w*.86),y+len(wrapped)*(size+12)+12),20,fill=(25,54,43,235))
            for line in wrapped:
                d.text((int(w*.13),y),line,font=font(size),fill='white');y+=size+12
        overlay_path=root/f'overlay-{i}.png';overlay.save(overlay_path)
        elapsed+=sound['duration'];end_frame=math.ceil(elapsed*25) if i==len(manifest)-1 else round(elapsed*25)
        frames=max(1,end_frame-frames_total);frames_total+=frames
        if p['render']['motion']=='gentle':
            movement=f"scale={w*2}:{h*2},zoompan=z='min(1.045,1+on*0.00012)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps=25"
        else: movement=f'scale={w}:{h},setsar=1'
        clip=root/f'clip-{i}.mp4'
        run(['ffmpeg','-hide_banner','-loglevel','error','-y','-threads','2','-filter_complex_threads','1','-loop','1','-framerate','25','-i',str(basepath),'-loop','1','-framerate','25','-i',str(overlay_path),'-filter_complex',f'[0:v]{movement}[bg];[bg][1:v]overlay=0:0,format=yuv420p[v]','-map','[v]','-frames:v',str(frames),'-c:v','libx264','-preset','veryfast','-crf','22','-threads','2','-an',str(clip)])
        clips.append(clip)
    listing=root/'clips.txt';listing.write_text('\n'.join(concat_entry(c) for c in clips))
    video=root/'silent.mp4'
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy',str(video)])
    args=['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(video),'-i',str(all_audio)]
    if p['render']['captions']:
        sub=root/'captions.ass';captions(manifest,w,h,sub)
        args+=['-vf','ass=captions.ass', '-c:v','libx264','-preset','veryfast','-crf','22','-threads','2']
    else: args+=['-c:v','copy']
    run(args+['-map','0:v:0','-map','1:a:0','-c:a','aac','-b:a','192k','-pix_fmt','yuv420p','-movflags','+faststart','-shortest',str(out)],cwd=root)
    return {'duration':duration(out),'width':w,'height':h}
