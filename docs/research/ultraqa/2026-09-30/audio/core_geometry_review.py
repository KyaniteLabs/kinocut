import json,subprocess
from pathlib import Path
from kinocut.engine_crop import crop
from kinocut.engine_preview import preview
from kinocut.ffmpeg_helpers import _run_ffprobe_json
r=Path('/workspace/.cache/kinocut-qa/audio-independent')
def run(a):return subprocess.run(['ffmpeg','-v','error','-y',*map(str,a)],stdin=subprocess.DEVNULL,capture_output=True,text=True,check=True,timeout=30)
source=r/'geometry.mp4'
run(['-f','lavfi','-i','color=c=red:s=160x90:r=25:d=1','-c:v','mpeg4',source])
rotated=r/'rotated-metadata.mp4'
run(['-display_rotation:v:0','90','-i',source,'-c','copy',rotated])
rows=[]
for label,action,args in [('odd_crop',crop,{'width':81,'height':45}),('rotated_preview',preview,{'scale_factor':1})]:
 p=source if label=='odd_crop' else rotated
 try:
  result=action(str(p),output_path=str(r/f'{label}.mp4'),**args)
  rows.append({'case':label,'source':_run_ffprobe_json(str(p)),'output':_run_ffprobe_json(result.output_path),'receipt':result.model_dump()})
 except Exception as e:rows.append({'case':label,'exception':type(e).__name__,'message':str(e)[:200]})
(r/'core_geometry_review.json').write_text(json.dumps(rows,indent=2)+'\n')
for row in rows:
 print(row['case'],row.get('receipt',{}).get('resolution'),[(s.get('width'),s.get('height'),s.get('sample_aspect_ratio'),s.get('display_aspect_ratio')) for s in row.get('output',{}).get('streams',[])])
