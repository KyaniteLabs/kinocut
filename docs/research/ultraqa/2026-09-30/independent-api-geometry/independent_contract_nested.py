import asyncio,json
from kinocut.server_tool_contracts import _ContractFastMCP
app=_ContractFastMCP('nested')
def handler(payload:dict)->dict:return payload
app.add_tool(handler)
value='['*1500+'0'+']'*1500
results={}
for key,args in {'pure':{'payload':value},'mixed':{'payload':value,'secret':'private-value'}}.items():
 try:
  result=asyncio.run(app.call_tool('handler',args));results[key]=str(result)
 except BaseException as e:results[key]={'exception':type(e).__name__,'message':str(e)}
print(json.dumps(results,indent=2))
