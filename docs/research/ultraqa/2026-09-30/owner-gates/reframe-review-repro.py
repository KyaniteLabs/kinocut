import importlib.util,json,hashlib
from pathlib import Path
from kinocut.ffmpeg_helpers import _reset_operation_inputs
spec=importlib.util.spec_from_file_location('fixtures','tests/test_reframe_render_receipts.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path('/workspace/.cache/kinocut-qa/reframe-review-fixtures');root.mkdir(exist_ok=True)
source=root/'source.mp4';m._source(source,(50,500));plan=m._plan(source,(50,500));original=plan.source.sha256
_reset_operation_inputs();m._source(source,(110,470));actual='sha256:'+hashlib.sha256(source.read_bytes()).hexdigest()
_reset_operation_inputs();receipt=m.render_reframe_plan(str(source),str(root/'output.mp4'),plan,'portrait')
print(json.dumps({'original_source':original,'actual_source':actual,'plan_hash_receipt':receipt.plan_sha256,'actual_plan_hash':plan.plan_sha256,'output_exists':(root/'output.mp4').is_file()}))
