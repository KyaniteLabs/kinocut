import json, os, pathlib, sys
root=pathlib.Path(__file__).parent
os.environ['KINOCUT_FFMPEG_EXECUTABLE']=sys.argv[1]
os.environ['KINOCUT_FFPROBE_EXECUTABLE']=sys.argv[2]
from kinocut.engine_audio_normalize import normalize_audio
from kinocut.engine_audio_mix import mix_audio
from kinocut.engine_audio_ops import add_audio,duck_audio
from kinocut.errors import MCPVideoError
source=root/'source.mp4'
results=[]
for byte in [None,255,16,32]:
  input=source if byte is None else root/f'damaged-{byte}.mp4'
  for op in [normalize_audio,mix_audio,add_audio,duck_audio]:
    output=root/f'operation-{op.__name__}-{byte}.mp4'; output.write_bytes(source.read_bytes()); before=output.read_bytes()
    row={'byte':byte,'operation':op.__name__,'ffmpeg':sys.argv[1],'ffprobe':sys.argv[2]}
    try:
      if op is normalize_audio: result=op(str(input),output_path=str(output))
      elif op is mix_audio: result=op(str(source),[{'path':str(input)}],str(output))
      else: result=op(str(source),str(input),output_path=str(output))
      row.update(success=result.success)
    except MCPVideoError as error:
      row.update(success=False,error_type=error.error_type,code=error.code,error=str(error)[:600])
    row['prior_preserved']=output.read_bytes()==before
    results.append(row); print(row,flush=True)
(root/'operations-native6.json').write_text(json.dumps(results,indent=2))
