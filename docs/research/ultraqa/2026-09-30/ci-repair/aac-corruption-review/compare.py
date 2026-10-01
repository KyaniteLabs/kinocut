import json, subprocess, pathlib, sys
root=pathlib.Path(__file__).parent
source=root/'source.mp4'
p=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','a:0','-show_packets','-show_entries','packet=pos,size','-of','json',str(source)],capture_output=True,text=True,check=True,stdin=subprocess.DEVNULL,timeout=30).stdout)['packets'][3]
results=[]
for byte in [255,0,1,16,32,64,127,128,170,85]:
    data=bytearray(source.read_bytes()); start,size=int(p['pos']),int(p['size']); data[start:start+size]=bytes([byte])*size
    damaged=root/f'damaged-{byte}.mp4'; damaged.write_bytes(data)
    for binary in sys.argv[1:] or ['ffmpeg']:
        process=subprocess.run([binary,'-v','error','-xerror','-i',str(damaged),'-map','0:a:0','-vn','-f','null','-'],capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=30)
        results.append({'byte':byte,'binary':binary,'code':process.returncode,'stderr':process.stderr[:1200]})
(root/'compare.json').write_text(json.dumps(results,indent=2))
for item in results: print(item['byte'],item['binary'],item['code'],item['stderr'][:120].replace('\n',' '))
