# RECONSTRUCTED original interception from retained tool history; not valid native-render evidence.
import subprocess,json,array,math
from pathlib import Path
from unittest.mock import patch
from kinocut import ffmpeg_helpers as helpers
from kinocut.engine_audio_mix import mix_audio
root=Path('/tmp/kinocut-native6-generator-review');silence=root/'silence.wav'
subprocess.run(['/usr/bin/ffmpeg','-v','error','-y','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','0.1',str(silence)],timeout=30,capture_output=True,check=True)
original=helpers._run_command
binary='/tmp/kinocut-ffmpeg6-source/'
def native(cmd,*args,**kwargs):
 cmd=list(cmd)
 if cmd[0] in ('ffmpeg','ffprobe'):cmd[0]=binary+cmd[0]
 return original(cmd,*args,**kwargs)
def rms(path,start):
 p=subprocess.run(['/usr/bin/ffmpeg','-v','error','-ss',str(start),'-i',str(path),'-t','0.15','-map','0:a:0','-ac','1','-f','f32le','-c:a','pcm_f32le','-'],timeout=30,capture_output=True,check=True)
 a=array.array('f');a.frombytes(p.stdout)
 val=math.sqrt(sum(v*v for v in a)/len(a))
 return 20*math.log10(max(val,1e-10))
rows=[]
for generator in (6,7):
 for mode in ('default','passthrough'):
  source=root/f'video{generator}-{mode}.mp4';output=root/f'mix6-video{generator}-{mode}.mp4'
  with patch('kinocut.ffmpeg_helpers._run_command',native):result=mix_audio(str(source),[{'path':str(silence)}],str(output))
  row={'generator':generator,'mode':mode,'native_mixer':6,'duration':result.duration,'rms_at_065':rms(output,.65),'rms_at_165':rms(output,1.65)}
  expected_duration=4 if generator==6 and mode=='default' else 3
  assert abs(row['duration']-expected_duration)<.08,row
  if expected_duration==3:assert row['rms_at_065']>-30,row
  else:assert row['rms_at_065']<-80 and row['rms_at_165']>-30,row
  rows.append(row)
Path('/tmp/kinocut-native6-mixer-origin-review.json').write_text(json.dumps(rows,indent=2))
print(json.dumps(rows,indent=2))
