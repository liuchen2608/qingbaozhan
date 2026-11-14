import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from hub.app import app, save_analysis
from hub import model
from hub.domain import ANALYSIS_FIELDS, CATEGORIES, PM_QUESTIONS, WEIGHTS

def analysis(score=None):
    return {**{k: '原文提及功能；实际效果待验证' for k in ANALYSIS_FIELDS},
            'category': CATEGORIES[0], 'tags': ['测试'],
            'pm_questions': {k: '依据原文分析，缺乏数据的部分未知' for k in PM_QUESTIONS},
            'scores': {k: {'score': v if score is None else 0, 'reason': '依据原文，评分为主观筛选'} for k, v in WEIGHTS.items()}}

class HubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'HUB_DB': str(Path(self.temp.name) / 'test.db'), 'MODEL_API_KEY': '', 'MODEL_ID': ''})
        self.environment.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.environment.stop()
        self.temp.cleanup()

    def add(self, **changes):
        value = {'title': '测试模型发布', 'url': 'https://x.com/example/status/123', 'content': '原文测试内容，不代表真实新闻。', 'author': '示例账号', 'published_at': '2026-11-14T08:00:00+08:00'}
        value.update(changes)
        response = self.client.post('/api/items', json=value)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_source_lifecycle(self):
        r = self.client.post('/api/sources', json={'name': '测试', 'url': 'https://x.com/example'})
        self.assertEqual(r.status_code, 201)
        sid = r.json()['id']
        self.assertEqual(self.client.put(f'/api/sources/{sid}', json={'name': '改名', 'url': 'https://x.com/example', 'enabled': False}).status_code, 200)
        self.assertFalse(self.client.get('/api/sources').json()[0]['enabled'])
        item = self.add(source_id=sid)
        self.client.delete(f'/api/sources/{sid}')
        self.assertIsNone(self.client.get('/api/items/'+str(item['id'])).json()['source_id'])

    def test_dedup_tweet_id(self):
        self.add()
        r = self.client.post('/api/items', json={'title':'重复','url':'https://twitter.com/other/status/123?s=20','published_at':'2026-11-14T00:00:00Z'})
        self.assertEqual(r.status_code, 409)

    def test_dedup_long_content(self):
        self.add(content='长正文测试' * 30)
        r=self.client.post('/api/items',json={'title':'重复正文','url':'https://example.com/news','content':'长正文测试 ' * 30,'published_at':'2026-11-14T00:00:00Z'})
        self.assertEqual(r.status_code,409)

    def test_scores_search_and_versions(self):
        item=self.add(); iid=item['id']
        a=analysis();a['total_score']=1
        r=self.client.put(f'/api/items/{iid}/analysis',json={'revision':1,'analysis':a})
        self.assertEqual(r.status_code,200,r.text); self.assertEqual(r.json()['score'],100)
        self.assertEqual(len(self.client.get('/api/items?q=功能&min_score=80').json()),1)
        self.assertEqual(len(self.client.get('/api/items?category=AI%20Agent').json()),0)
        item.update(notes='个人笔记',favorite=True)
        r=self.client.put(f'/api/items/{iid}',json=item)
        self.assertEqual(r.json()['revision'],1);self.assertIsNotNone(r.json()['analysis'])
        item.update(content='原文发生变化')
        r=self.client.put(f'/api/items/{iid}',json=item)
        self.assertEqual(r.json()['revision'],2);self.assertIsNone(r.json()['analysis'])
        self.assertEqual(len(self.client.get(f'/api/items/{iid}/versions').json()),1)
        self.assertEqual(self.client.put(f'/api/items/{iid}/analysis',json={'revision':1,'analysis':a}).status_code,409)

    def test_score_validation(self):
        iid=self.add()['id'];a=analysis();a['scores']['技术创新价值']['score']=26
        self.assertEqual(self.client.put(f'/api/items/{iid}/analysis',json={'revision':1,'analysis':a}).status_code,422)
        self.assertIsNone(self.client.get(f'/api/items/{iid}').json()['analysis'])

    def test_missing_model_and_empty_body(self):
        iid=self.add()['id']
        self.assertFalse(self.client.get('/api/status').json()['model_configured'])
        self.assertEqual(self.client.post(f'/api/items/{iid}/analyze').status_code,502)
        with patch.dict(os.environ,{'MODEL_API_KEY':'test-only','MODEL_ID':'mock'}):
            self.assertTrue(self.client.get('/api/status').json()['model_configured'])
            empty=self.add(url='https://example.com/empty',content='')['id']
            self.assertEqual(self.client.post(f'/api/items/{empty}/analyze').status_code,502)

    def test_timezone_and_report_limit(self):
        for n in range(12):
            iid=self.add(url=f'https://example.com/{n}',published_at='2026-11-13T16:00:00Z')['id']
            save_analysis(iid,1,analysis(),'manual')
        outside=self.add(url='https://example.com/outside',published_at='2026-11-14T16:00:00Z')['id']
        save_analysis(outside,1,analysis(),'manual')
        report=self.client.get('/api/report?day=2026-11-14').json()
        self.assertEqual(report['count'],10)
        self.assertIn('https://example.com/',report['markdown'])
        self.assertEqual(len(self.client.get('/api/items?start=2026-11-14&end=2026-11-14').json()),12)
        self.assertEqual(self.client.get('/api/report?day=2026-11-14&period=weekly').json()['count'],10)

    def test_empty_report_no_padding(self):
        self.add()
        r=self.client.get('/api/report?day=2026-11-14').json()
        self.assertEqual(r['count'],0);self.assertIn('暂无符合',r['markdown'])

    def test_csv_json_xlsx_import(self):
        r=self.client.post('/api/import/sources', files={'file':('sources.csv','name,url,enabled\n测试,https://x.com/test,false\n重复,https://x.com/test,true\n坏链接,javascript:alert(1),true\n'.encode(),'text/csv')})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['imported'],1);self.assertEqual(r.json()['duplicates'],1);self.assertEqual(len(r.json()['errors']),1)
        self.assertFalse(self.client.get('/api/sources').json()[0]['enabled'])
        self.assertEqual(self.client.post('/api/import/items',files={'file':('items.json',json.dumps([{'title':'导入','url':'https://example.com/1','published_at':'2026-11-14T00:00:00Z'}]),'application/json')}).json()['imported'],1)
        from openpyxl import Workbook
        book=Workbook();sheet=book.active;sheet.append(['name','url']);sheet.append(['第二个来源','https://example.com/source']);out=io.BytesIO();book.save(out)
        self.assertEqual(self.client.post('/api/import/sources',files={'file':('sources.xlsx',out.getvalue(),'application/octet-stream')}).json()['imported'],1)

    def test_export_real_xlsx_and_formula_safety(self):
        self.add(title='=1+1',notes='@SUM(1)')
        r=self.client.get('/api/export?format=xlsx')
        self.assertEqual(r.status_code,200)
        sheet=load_workbook(io.BytesIO(r.content)).active
        self.assertEqual(sheet['A2'].value,'=1+1');self.assertEqual(sheet['A2'].data_type,'s')
        self.assertIn('https://x.com/',self.client.get('/api/export').text)

    def test_invalid_inputs_and_origin(self):
        self.assertEqual(self.client.post('/api/sources',json={'name':'bad','url':'javascript:alert(1)'}).status_code,422)
        self.assertEqual(self.client.post('/api/items',json={'title':'无时区','url':'https://example.com','published_at':'2026-11-14T12:00:00'}).status_code,422)
        self.assertEqual(self.client.post('/api/sources',headers={'Origin':'https://evil.example'},json={'name':'bad','url':'https://example.com'}).status_code,403)
        self.assertEqual(self.client.get('/api/items',headers={'Host':'evil.example'}).status_code,400)
        self.assertEqual(self.client.get('/api/items/999').status_code,404)

    def test_model_protocols(self):
        for provider in ('openai','anthropic'):
            seen=[]
            def respond(request):
                seen.append(request)
                if provider=='openai':
                    return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(analysis())}}]})
                return httpx.Response(200,json={'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(analysis())}]})
            original=httpx.AsyncClient
            with patch.dict(os.environ,{'MODEL_PROVIDER':provider,'MODEL_BASE_URL':'https://model.example','MODEL_API_KEY':'test-only','MODEL_ID':'mock-model'}), patch.object(model.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(respond),**kw)):
                iid=self.add(url='https://example.com/'+provider)['id']
                r=self.client.post(f'/api/items/{iid}/analyze')
                self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['score'],100)
            self.assertEqual(seen[0].url.path,'/chat/completions' if provider=='openai' else '/v1/messages')

    def test_malformed_model_does_not_save(self):
        original=httpx.AsyncClient
        with patch.dict(os.environ,{'MODEL_PROVIDER':'openai','MODEL_API_KEY':'test-only','MODEL_ID':'mock'}), patch.object(model.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':'not json'}}]})),**kw)):
            iid=self.add()['id']
            self.assertEqual(self.client.post(f'/api/items/{iid}/analyze').status_code,502)
            self.assertIsNone(self.client.get(f'/api/items/{iid}').json()['analysis'])

    def test_public_deployment_access(self):
        with patch.dict(os.environ, {'HUB_PUBLIC_MODE':'1', 'HUB_USERNAME':'owner', 'HUB_PASSWORD':'test-password-123456', 'RENDER_EXTERNAL_HOSTNAME':'hub.example'}):
            with TestClient(app, base_url='https://hub.example') as client:
                for path in ('/', '/app.js', '/api/items', '/api/export', '/docs'):
                    r=client.get(path)
                    self.assertEqual(r.status_code,401,path)
                    self.assertIn('Basic',r.headers['www-authenticate'])
                self.assertEqual(client.get('/healthz').status_code,200)
                self.assertEqual(client.get('/api/items',auth=('owner','wrong')).status_code,401)
                self.assertEqual(client.get('/api/items',headers={'Authorization':'Basic malformed'}).status_code,401)
                r=client.get('/',auth=('owner','test-password-123456'))
                self.assertEqual(r.status_code,200)
                self.assertEqual(r.headers['cache-control'],'no-store')
                value={'name':'部署来源','url':'https://example.com'}
                self.assertEqual(client.post('/api/sources',json=value,auth=('owner','test-password-123456'),headers={'Origin':'https://evil.example'}).status_code,403)
                self.assertEqual(client.post('/api/sources',json=value,auth=('owner','test-password-123456'),headers={'Origin':'https://hub.example'}).status_code,201)
                self.assertEqual(client.get('/',auth=('owner','test-password-123456'),headers={'Host':'evil.example'}).status_code,400)

    def test_public_configuration_fails_closed(self):
        with patch.dict(os.environ,{'HUB_PUBLIC_MODE':'1','HUB_PASSWORD':'','HUB_USERNAME':''}):
            with self.assertRaises(RuntimeError):
                with TestClient(app):
                    pass

if __name__=='__main__':
    unittest.main()
