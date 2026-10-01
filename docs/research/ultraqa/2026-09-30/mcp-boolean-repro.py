import asyncio,json,sys,wave
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from jsonschema import Draft202012Validator
p=Path('/workspace/.cache/kinocut-qa/bool-parity.wav')
with wave.open(str(p),'wb') as w:
 w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(b'\0\0'*48000)
async def main():
 async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','kinocut','--mcp'])) as (r,w),ClientSession(r,w) as s:
  await s.initialize(); tools=await s.list_tools(); t=next(t for t in tools.tools if t.name=='video_audio_waveform')
  args={'input_path':str(p),'bins':True}; result=await s.call_tool(t.name,args)
  print(json.dumps({'case':'numeric_boolean_bins','schema_accepts':Draft202012Validator(t.inputSchema).is_valid(args),'isError':result.isError,'success':result.structuredContent.get('success'),'returned_peak_count':len(result.structuredContent.get('peaks',[]))}))
asyncio.run(main())
