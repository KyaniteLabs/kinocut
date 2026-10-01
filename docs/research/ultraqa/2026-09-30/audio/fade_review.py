import json,re,subprocess
from pathlib import Path
from kinocut.engine_fade import fade
from kinocut.ffmpeg_helpers import _run_ffprobe_json
r=Path('/workspace/.cache/kinocut-qa/audio-independent')
def run(args):return subprocess.run(['ffmpeg','-hide_banner','-y',*map(str,args)],stdin=subprocess.DEVNULL,capture_output=True,text=True,check=True,timeout=30)
def luma(path,time):
 p=run(['-ss',time,'-i',path,'-map','0:v:0','-an','-vf','signalstats,metadata=print:key=lavfi.signalstats.YAVG','-frames:v','1','-f','null','-'])
 values=re.findall(r'lavfi.signalstats.YAVG=([\d.]+)',p.stderr)
 return float(values[0]) if values else None
rows=[]
for label,audio_dur,video_start in [('matched',1,0),('long_audio',3,0),('late_picture',3,1)]:
 source=r/f'{label}.mp4';out=r/f'{label}-faded.mp4'
 run(['-itsoffset',video_start,'-f','lavfi','-i','color=c=white:s=160x90:r=25:d=1','-f','lavfi','-i',f'sine=frequency=440:sample_rate=48000:d={audio_dur}','-map','0:v:0','-map','1:a:0','-c:v','mpeg4','-fps_mode','passthrough','-c:a','aac',source])
 result=fade(str(source),fade_in=.5 if video_start else 0,fade_out=0 if video_start else .5,output_path=str(out))
 point=video_start+.9 if not video_start else video_start+.08
 rows.append({'case':label,'source':_run_ffprobe_json(str(source)),'output':_run_ffprobe_json(str(out)), 'sample_pts':point,'source_luma':luma(source,point),'output_luma':luma(out,point),'receipt':result.model_dump()})
(r/'fade_review.json').write_text(json.dumps(rows,indent=2)+'\n')
for row in rows:print(row['case'],row['sample_pts'],row['source_luma'],row['output_luma'])
