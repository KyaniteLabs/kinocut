"""Fresh-process source-bound runtime evidence; no speech model imports/calls."""
import argparse,hashlib,json,resource,subprocess,tempfile,time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
p=argparse.ArgumentParser();p.add_argument('mode');p.add_argument('--rate',type=int,default=48000);args=p.parse_args()
ROOT=Path('/workspace/.cache/kinocut-qa/latency')
if args.mode in {'baseline_signal','fixed_signal'}:
 from kinocut.quality_guardrails import VisualQualityGuardrails
 import kinocut.quality_guardrails as module
 source=ROOT/'source-28800.mp4'
 start=time.perf_counter()
 means=VisualQualityGuardrails()._get_all_signalstats(str(source))
 elapsed=time.perf_counter()-start
 result=dict(means=means,fixture_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),module_path=str(Path(module.__file__).resolve()),source_sha256=hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),frames=28800)
elif args.mode=='baseline_asr_preprocessing':
 source=ROOT/f'source-{args.rate}.pcm'
 start=time.perf_counter()
 pcm=np.fromfile(source,dtype='<i2').astype(np.float32)/32768.0
 count=round(len(pcm)*16000/args.rate)
 positions=np.arange(count,dtype=np.float64)*args.rate/16000
 pcm=np.interp(positions,np.arange(len(pcm)),pcm).astype(np.float32)
 elapsed=time.perf_counter()-start
 result=dict(input_frames=source.stat().st_size//2,output_frames=len(pcm),fixture_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),baseline_source_revision='e9f6cac77cb390c73c919bdcd385b775a6a3c7ef',baseline_source_path='kinocut_sound/public/asr_worker.py',baseline_scope='Original recognize() preprocessing verbatim; optional torch/Whisper imports and all inference excluded')
elif args.mode=='fixed_asr_preprocessing':
 from kinocut_sound.public import asr_resample
 from kinocut_sound.qa.meter_process import run_meter_sync
 source=ROOT/f'source-{args.rate}.pcm'
 binary=asr_resample.installed_resampler()
 start=time.perf_counter()
 version=asr_resample.backend_version(run_meter_sync([binary,'-version'],10))
 with tempfile.TemporaryDirectory(dir=ROOT,prefix='resample-') as folder:
  root=Path(folder);(root/'source.pcm').write_bytes(source.read_bytes())
  frames=source.stat().st_size//2
  job=SimpleNamespace(root=root,rate=args.rate,duration=frames/args.rate)
  run_meter_sync(asr_resample.command(binary,job),10)
  raw=(root/'source.f32').read_bytes();assert len(raw)==round(frames/args.rate*16000)*4;del raw
  pcm=np.fromfile(root/'source.f32',dtype='<f4');assert np.isfinite(pcm).all()
 elapsed=time.perf_counter()-start
 result=dict(input_frames=frames,output_frames=len(pcm),fixture_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),profile=asr_resample.RESAMPLING_ID,ffmpeg_version=version,source_sha256=hashlib.sha256(Path(asr_resample.__file__).read_bytes()).hexdigest(),scope='FFmpeg version+conversion, input staging, parent length validation and float32 worker load; no model/checkpoint/inference')
result.update(mode=args.mode,rate=args.rate,wall_seconds=elapsed,parent_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,child_peak_rss_mib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss/1024,python=__import__('sys').version,numpy=np.__version__)
print(json.dumps(result,sort_keys=True))
