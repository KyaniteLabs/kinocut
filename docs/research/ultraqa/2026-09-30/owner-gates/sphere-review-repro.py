import hashlib,json,subprocess
from pathlib import Path
from kinocut.te.sphere_director import apply_director
from kinocut.te.sphere_plan import propose_sphere_plan, decide_sphere_plan
from kinocut.te.sphere_render import render_sphere_plan
from kinocut.ffmpeg_helpers import _reset_operation_inputs
root=Path('/workspace/.cache/kinocut-qa/sphere-review-fixtures');root.mkdir(exist_ok=True)
source=root/'source.mp4'
def fixture(color):
 subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'color={color}:s=320x160:r=5:d=0.4','-c:v','libx264',str(source)],check=True,timeout=30)
fixture('red')
plan=propose_sphere_plan(str(source),writer_kind='single');plan['output']['width']=64;plan['output']['height']=32
original=plan['source']['sha256']
fixture('blue');actual='sha256:'+hashlib.sha256(source.read_bytes()).hexdigest()
_reset_operation_inputs()
try:
 result=render_sphere_plan(decide_sphere_plan(plan,'approve'),str(root/'output.mp4'),allow_fail=True)
 print(json.dumps({'source_original':original,'source_actual':actual,'render_status':result['status'],'receipt_source':result['source']['sha256']}))
except Exception as e: print('render exception',type(e).__name__,str(e))
_reset_operation_inputs()
def mutate_then_fail(candidate):
 candidate['source']['path']='/tmp/unrequested-private-source.mp4'
 candidate['status']='approved'
 candidate['output']['width']=float('nan')
 raise RuntimeError('backend unavailable')
fallback=apply_director(str(source),propose=mutate_then_fail)
print(json.dumps({'fallback_source':fallback['source']['path'],'fallback_status':fallback['status'],'fallback_width':fallback['output']['width'],'unavailable':fallback['writer']['unavailable']}))
