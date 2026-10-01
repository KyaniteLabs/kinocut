import asyncio,hashlib,json,importlib.metadata
from pathlib import Path
from jsonschema import Draft202012Validator
from kinocut.server import mcp
async def main():
 tools=await mcp.list_tools();rows=[]
 for t in tools:
  Draft202012Validator.check_schema(t.inputSchema)
  assert set(t.inputSchema.get('required',[])) <= set(t.inputSchema['properties'])
  model=mcp._tool_manager.get_tool(t.name).fn_metadata.arg_model
  assert model.model_config['extra']=='forbid' and t.inputSchema.get('additionalProperties') is False
  rows.append({'name':t.name,'required':t.inputSchema.get('required',[]),'properties':list(t.inputSchema['properties']),'additionalProperties':False,'schema_sha256':hashlib.sha256(json.dumps(t.inputSchema,sort_keys=True).encode()).hexdigest()})
 out={'baseline_commit':'e9f6cac77cb390c73c919bdcd385b775a6a3c7ef','source_state':'dirty working tree after merge','observed_utc':'2026-10-01','mcp_sdk':importlib.metadata.version('mcp'),'pydantic':importlib.metadata.version('pydantic'),'all_tool_count':len(rows),'all_tools':rows,'source_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ['kinocut/server_app.py','kinocut/server_tool_contracts.py']},'limits':['Structural schema and authoritative argument-model checks only; not execution of all optional tool handlers.']}
 Path('docs/research/ultraqa/2026-09-30/api-contracts-current.json').write_text(json.dumps(out,indent=2)+'\n')
 print('201 schema/model contracts verified' if len(rows)==201 else len(rows))
asyncio.run(main())
