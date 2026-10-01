import asyncio,json,sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
 async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','kinocut','--mcp'])) as (r,w),ClientSession(r,w) as s:
  await s.initialize()
  for args in ({'unknown':'PRIVATESECRET_SENTINEL'},{'input_path':{'secret':'PRIVATESECRET_SENTINEL'},'unknown':'PRIVATESECRET_SENTINEL'}):
   result=await s.call_tool('video_info',args)
   print(json.dumps({'case':'missing' if 'input_path' not in args else 'invalid_type','isError':result.isError,'secret_echo':'PRIVATESECRET_SENTINEL' in json.dumps(result.model_dump()),'text_length':sum(len(c.text) for c in result.content if hasattr(c,'text'))}))
asyncio.run(main())
