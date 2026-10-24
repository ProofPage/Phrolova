import asyncio, functools, http.server, json, os, pathlib, shutil, signal, subprocess, sys, tempfile, threading, time, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]; PY=sys.executable
(ROOT/"audit-evidence").mkdir(exist_ok=True)
work=pathlib.Path(tempfile.mkdtemp(prefix='phrolova-audit-')); shutil.copytree(ROOT/'backend', work/'backend',ignore=shutil.ignore_patterns('data','__pycache__','.env')); media=work/'media'; media.mkdir(); out=work/'recordings'; out.mkdir()
subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc=size=320x180:rate=24','-f','lavfi','-i','sine=frequency=440','-t','12','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(media/'sample.mp4')],check=True)
subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(media/'sample.mp4'),'-c','copy','-f','hls','-hls_time','2','-hls_list_size','0',str(media/'sample.m3u8')],check=True)
class Handler(http.server.SimpleHTTPRequestHandler):
 def copyfile(self, source, outputfile):
  if self.path.startswith('/slow.mp4'):
   try:
    while chunk := source.read(1024):
     outputfile.write(chunk); outputfile.flush(); time.sleep(.1)
   except (BrokenPipeError, ConnectionResetError): pass
  else: super().copyfile(source, outputfile)
 def log_message(self,*args): pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(media))); threading.Thread(target=server.serve_forever,daemon=True).start(); media_url=f'http://127.0.0.1:{server.server_port}'
env=dict(os.environ,HOST='127.0.0.1',PORT='18080',DOWNLOAD_DIR=str(out),MONITOR_INTERVAL='60',NID_AUT='',NID_SES='',DISCORD_BOT_TOKEN='',DISCORD_WEBHOOK_URL='')
for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'): env.pop(key,None)
base='http://127.0.0.1:18080'; log=open(ROOT/'audit-evidence/server.txt','w'); process=None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def request(path,data=None,method=None):
 req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'},method=method)
 with opener.open(req,timeout=5) as response: return response.read()
def start():
 p=subprocess.Popen([PY,'run.py'],cwd=work/'backend',env=env,stdout=log,stderr=log)
 for _ in range(100):
  try: request('/health'); return p
  except Exception: time.sleep(.1)
 raise RuntimeError('server did not boot')
def stop(p,sig):
 p.send_signal(sig); p.wait(timeout=25); assert p.returncode==0 or p.returncode==-sig, p.returncode
try:
 shutil.copyfile(media/'sample.mp4', media/'slow.mp4')
 process=start(); print('BOOT/HEALTH',request('/health').decode()); assert b'<html' in request('/').lower(); print('SPA_HTML PASS'); routes=json.loads(request('/openapi.json')); print('OPENAPI_ROUTES',len(routes['paths']))
 req=urllib.request.Request(base+'/api/events'); response=opener.open(req,timeout=5); print('SSE',response.readline().decode().strip()); response.close()
 request('/api/tags',{'name':'검수-persistent'}); print('TAG_WRITE PASS')
 job=json.loads(request('/api/vod/download',{'url':media_url+'/sample.mp4','output_dir':str(out)}))['task_id']
 for _ in range(100):
  status=json.loads(request('/api/vod/status/'+job))
  if status['state'] in ('completed','error'): break
  time.sleep(.1)
 assert status['state']=='completed',status; print('LOCAL_VOD PASS',status['output_path']); assert pathlib.Path(status['output_path']).stat().st_size>0
 cancel_id=json.loads(request('/api/vod/download',{'url':media_url+'/slow.mp4','output_dir':str(out)}))['task_id']
 for _ in range(50):
  cancel_status=json.loads(request('/api/vod/status/'+cancel_id))
  if cancel_status['state']=='downloading': break
  time.sleep(.1)
 print('CANCEL_REQUEST',request('/api/vod/'+cancel_id+'/cancel',{}).decode())
 for _ in range(200):
  cancel_status=json.loads(request('/api/vod/status/'+cancel_id))
  if cancel_status['state']=='idle': break
  time.sleep(.1)
 assert cancel_status['state']=='idle',cancel_status
 print('LOCAL_VOD_CANCEL PASS')
 request('/api/settings/vod',{'keep_download_parts':True},'PUT'); assert (work/'.env').exists(); print('ENV_WRITE PASS')
 stop(process,signal.SIGTERM); process=None; print('SIGTERM PASS'); process=start(); assert '검수-persistent' in request('/api/tags').decode(); assert json.loads(request('/api/vod/status/'+job))['state']=='completed'; assert json.loads(request('/api/settings'))['keep_download_parts'] is True; print('RESTART_DB_HISTORY_ENV PASS'); stop(process,signal.SIGINT); process=None; print('SIGINT PASS')
 # Actual HLS transport + media pipe; mock only the site-specific URL extractor.
 sys.path.insert(0,str(work/'backend'))
 from app.core.config import get_settings
 from app.engine.pipeline.ytdlp import YtdlpLivePipeline
 from app.engine.pipeline.state import RecordingState
 async def live():
  settings=get_settings(); settings.live_format='ts'; settings.chzzk_stream_mode='standard'
  pipeline=YtdlpLivePipeline(channel_id='audit')
  async def extract(*args,**kwargs): return media_url+'/sample.m3u8',{},None
  pipeline._extract_hls_url=extract
  path=await pipeline.start_recording('https://example.test/live',output_dir=str(out),filename='검수-live.ts')
  for _ in range(100):
   if pathlib.Path(path).exists() and pathlib.Path(path).stat().st_size>0: break
   await asyncio.sleep(.1)
  await pipeline.stop_recording(); assert pathlib.Path(path).stat().st_size>0
  subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1',path],check=True)
  print('STREAMLINK_HLS_FFMPEG_TS PASS',pipeline.state)
 asyncio.run(live())
 for fmt in ('mp4','mkv'):
  target=out/f'검수-convert.{fmt}'; subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(out/'검수-live.ts'),'-c','copy',str(target)],check=True); print('REMUX',fmt,'PASS')
 print('ARTIFACT_DIR',work)
finally:
 if process and process.poll() is None: process.terminate(); process.wait(timeout=25)
 server.shutdown(); log.close()
