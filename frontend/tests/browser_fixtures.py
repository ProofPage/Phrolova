"""외부 서비스 없이 UI 회귀 검사를 실행하기 위한 샘플 API 응답이다."""
import json
from mobile_fixtures import FIX

LONG = FIX["long"]

async def mock(route):
    from urllib.parse import urlparse
    pathname=urlparse(route.request.url).path
    if not pathname.startswith('/api/'): return await route.continue_()
    path=pathname[5:]
    data={}
    if path=='setup/status': data={'needs_setup':False}
    elif path=='settings': data=FIX['settings']
    elif path=='vod/status': data={'tasks':FIX['tasks'],'active_count':1,'imports':FIX.get('imports',[])}
    elif path=='platforms/channels': data=FIX['channels']
    elif path=='platforms/status': data={x:{'enabled':True,'authenticated':True} for x in ['chzzk','youtube','x_spaces']}
    elif path=='tags': data={'tags':['tag',LONG]}
    elif path.startswith('system/update'): data={'has_update':True,'current_version':'2.0.47-'+LONG,'latest_version':'2.0.48-'+LONG,'release_notes':LONG,'environment':'linux-native','download_url':'https://github.com/ProofPage/Phrolova/releases'}
    elif path=='stats/': data=FIX['stats']
    elif path=='chat/files': data=[{'file_id':'1','filename':LONG+'.jsonl','channel':LONG,'size_bytes':4096,'message_count':10000,'created_at':'2026-10-07T12:00:00Z'}]
    elif path.endswith('/messages'): data={'messages':[{'nickname':LONG,'message':LONG+' https://example.com/'+LONG+'😀','timestamp':'2026-10-07T12:00:00Z'}],'total':10000,'page':1,'limit':100,'has_next':True}
    elif path=='system/logs': data=[{'filename':'service.log','size_bytes':4096,'modified_at':'2026-10-07T12:00:00Z'}]
    elif path.startswith('system/logs/'): data={'content':LONG*5,'total_lines':1}
    elif path=='settings/browse-dirs': data={'current':'/'+LONG,'parent':'/','dirs':[{'name':LONG,'path':'/'+LONG}]}
    elif path=='events': return await route.fulfill(content_type='text/event-stream',body='data: '+json.dumps({'type':'status_update','data':FIX['channels']})+'\n\n')
    elif path.startswith('stream/preview/'): return await route.fulfill(status=503,json={'detail':'test unavailable'})
    elif path=='settings/discord/status': data={'available':True,'transports':[],'pending':0}
    return await route.fulfill(json=data)
