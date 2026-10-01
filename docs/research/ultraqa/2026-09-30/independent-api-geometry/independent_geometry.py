import json,subprocess
from pathlib import Path
from kinocut.engine_crop import crop
from kinocut.engine_fade import fade
from kinocut.ffmpeg_helpers import _run_ffmpeg,_run_ffprobe_json,_reset_operation_inputs
root=Path('/workspace/.cache/kinocut-qa/latency/geometry-review');root.mkdir(exist_ok=True)
source=root/'delayed.mp4'
_run_ffmpeg(['-itsoffset','1','-f','lavfi','-i','testsrc2=s=160x90:r=25:d=1','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:d=3','-map','0:v:0','-map','1:a:0','-c:v','mpeg4','-fps_mode','passthrough','-c:a','aac',str(source)])
results={}
for operation in ('source','crop','fade'):
 _reset_operation_inputs()
 output=source if operation=='source' else root/(operation+'.mp4')
 if operation=='crop':crop(str(source),width=100,height=80,output_path=str(output))
 if operation=='fade':fade(str(source),fade_in=.5,fade_out=0,output_path=str(output))
 meta=_run_ffprobe_json(str(output));results[operation]={'format':meta['format'],'streams':[{k:s.get(k) for k in ('codec_type','start_time','duration','nb_frames','r_frame_rate','avg_frame_rate')} for s in meta['streams']]}
(root/'result.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
