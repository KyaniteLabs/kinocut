import os,subprocess,json,hashlib
from pathlib import Path
from types import SimpleNamespace
from kinocut.engine_audio_validation import _run_audio_ffmpeg
from kinocut.errors import ProcessingError
native='/workspace/.cache/kinocut-qa/native6/source/ffmpeg'
root=Path('/workspace/.cache/kinocut-qa/aac-corruption-review')
rows=[]
for color in [False,True]:
 for name in ['source.mp4','damaged-16.mp4']:
  env={**os.environ};env.pop('AV_LOG_FORCE_COLOR',None)
  if color: env['AV_LOG_FORCE_COLOR']='1'
  def run(args):
   return subprocess.run([native,*args],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=30,env=env)
  try:
   result=_run_audio_ffmpeg(['-hide_banner','-v','error','-xerror','-i',str(root/name),'-map','0:a:0','-vn','-f','null','-'],runner=run)
   assert name=='source.mp4'
   rows.append({'input':name,'color':color,'accepted':True,'returncode':result.returncode})
  except ProcessingError as error:
   assert name=='damaged-16.mp4' and error.returncode==0 and error.code=='ffmpeg_exit_0'
   assert len(error.full_stderr.encode('utf-8'))<=4096
   rows.append({'input':name,'color':color,'accepted':False,'returncode':error.returncode,'code':error.code})
for color in [False,True]:
 diagnostic='[error] bare decoder failure'
 if color: diagnostic='\x1b[31m'+diagnostic+'\x1b[0m'
 try: _run_audio_ffmpeg([],runner=lambda args:SimpleNamespace(returncode=0,stderr=diagnostic))
 except ProcessingError as error: assert error.returncode==0;rows.append({'bare':True,'color':color,'rejected':True})
 else: raise AssertionError('bare severity was ignored')
for level in ['info','warning']:
 result=SimpleNamespace(returncode=0,stderr=f'[{level}] [error] literal filename\n')
 assert _run_audio_ffmpeg([],runner=lambda args:result) is result
 rows.append({'nonfatal_literal':level,'accepted':True})
proof={'binary':native,'binary_sha256':hashlib.sha256(Path(native).read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256(Path('/workspace/kinocut/kinocut/engine_audio_validation.py').read_bytes()).hexdigest(),'rows':rows}
Path('/workspace/.cache/kinocut-qa/native6/audio-final-independent-review.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2))
