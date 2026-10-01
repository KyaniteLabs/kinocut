"""Measured passband/stopband controls; excludes Whisper/recognition completely."""
import hashlib,json,tempfile
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from kinocut_sound.public import asr_resample
from kinocut_sound.qa.meter_process import run_meter_sync
root=Path('/workspace/.cache/kinocut-qa/latency')
binary=asr_resample.installed_resampler()
version=asr_resample.backend_version(run_meter_sync([binary,'-version'],10))
rate=48000
t=np.arange(rate)/rate
source=np.rint(12000*np.sin(2*np.pi*1000*t)+12000*np.sin(2*np.pi*11000*t)).astype('<i2')
with tempfile.TemporaryDirectory(dir=root,prefix='spectral-') as temp:
 folder=Path(temp);(folder/'source.pcm').write_bytes(source.tobytes())
 run_meter_sync(asr_resample.command(binary,SimpleNamespace(root=folder,rate=rate,duration=1)),10)
 fixed=np.fromfile(folder/'source.f32',dtype='<f4')
old=np.interp(np.arange(16000)*3,np.arange(len(source)),source.astype(np.float32)/32768).astype(np.float32)
def measure(data):
 middle=data[1600:-1600]
 t=np.arange(len(middle))/16000
 def amplitude(freq):return float(abs(2*np.mean(middle*np.exp(-2j*np.pi*freq*t))))
 return dict(frames=len(data),finite=bool(np.isfinite(data).all()),passband_1000hz_amplitude=amplitude(1000),alias_5000hz_amplitude=amplitude(5000),alias_5000hz_dbfs=20*float(np.log10(max(amplitude(5000),1e-30))))
result=dict(input_rate_hz=rate,input_frames=len(source),source_sha256=hashlib.sha256(source.tobytes()).hexdigest(),output_rate_hz=16000,expected_output_frames=16000,edge_exclusion_frames=1600,baseline_linear=measure(old),fixed_bandlimited=measure(fixed),ffmpeg_version=version,numpy_version=np.__version__,scope='PCM frontend tone controls only; no model, speech corpus, listening or WER evaluation')
(root/'spectrum.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
