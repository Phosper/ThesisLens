import datetime as dt
import json
import gzip
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import announcements as a
import core
import knowledge
import retrieval
import research

def candidate(sid='TEST',date='2026-09-30',code='000333',**fields):
    return dict(source_id=sid,locator='PDF第4页',pdf_page=4,text='经营活动现金流量净额',publication_date=date,
                stock_code=code,report_period='2026-H1',kind='financial',title='测试财报',company=core.COMPANIES.get(code),**fields)

class SemanticTests(unittest.TestCase):
    def test_filters_are_enforced_on_every_recall_path(self):
        rows=[candidate(),candidate('FUTURE','2026-10-07'),candidate('OTHER',code='000651'),candidate('IND',code=None)]
        with patch.object(core,'search',return_value=rows):
            got=retrieval.collect_candidates(['赚的钱收到没','经营现金流'],'000333','2026-10-06',period='2026-H1',include_industry=False)
        self.assertEqual([r['source_id'] for r in got],['TEST'])
        self.assertAlmostEqual(got[0]['fusion_score'],2/61,6)

    def test_ranking_cannot_invent_or_duplicate_source_ids(self):
        for rows in [[{'id':'C99','relevance':3,'reason':'好'}],[{'id':'C1','relevance':True,'reason':'好'}],[],[{'id':'C1','relevance':4,'reason':'好'}]]:
            with self.assertRaises(ValueError):retrieval.validate_ranking({'ranking':rows},[candidate()])
        rows=[{'id':'C1','relevance':2,'reason':'背景'},{'id':'C1','relevance':3,'reason':'直接'}]
        with self.assertRaises(ValueError):retrieval.validate_ranking({'ranking':rows},[candidate(),candidate('B')])

    def test_model_can_only_reorder_original_passages(self):
        first=candidate();second=candidate('B');second['text']='应收账款变化的原页文字'
        ranking={'ranking':[{'id':'C1','relevance':1,'reason':'背景'},{'id':'C2','relevance':3,'reason':'直接对应问题'}]}
        got=retrieval.validate_ranking(ranking,[first,second])
        self.assertEqual(got[0]['source_id'],'B');self.assertEqual(got[0]['text'],second['text'])
        self.assertEqual(got[0]['pdf_page'],4)

    def test_semantic_failure_returns_local_results_and_warning(self):
        with patch.object(model_module(),'complete',side_effect=ValueError('模型返回格式无效')),patch.object(core,'search',return_value=[candidate()]):
            got=retrieval.search('赚的钱有没有收到','000333','2026-10-06',persist=False)
        self.assertEqual(got['mode'],'keyword');self.assertTrue(got['warnings']);self.assertEqual(got['data'][0]['source_id'],'TEST')

    def test_full_semantic_result_persists_filters_prompts_and_reasons(self):
        with tempfile.TemporaryDirectory(dir=core.DATA) as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(core.DATA.resolve()))
            responses=[({'queries':['经营现金流 净利润'],'intent':'核验现金转化'},{'model':'test','usage':{}}),
                       ({'ranking':[{'id':'C1','relevance':3,'reason':'经营现金流事实'}]},{'model':'test','usage':{}})]
            with patch.object(retrieval,'DB',Path(folder)/'retrieve.sqlite3'),patch.object(model_module(),'complete',side_effect=responses),patch.object(core,'search',return_value=[candidate()]):
                got=retrieval.search('赚的钱有没有收到','000333','2026-10-06')
                stored=retrieval.get(got['id'])
            self.assertEqual(stored['mode'],'semantic');self.assertEqual(len(stored['model_calls']),2)
            self.assertEqual(stored['data'][0]['semantic_relevance'],3)

    def test_semantic_candidates_do_not_crowd_out_primary_tables_and_latest_policy(self):
        core.ensure_index()
        extra=[candidate(f'DUMMY{i}',ocr=0) for i in range(24)]
        evidence,metrics=research.collect_evidence('000333','2026-10-06','存货和现金流','2026-H1',semantic_rows=extra)
        self.assertTrue({'IND_010','IND_020','IND_022'}.issubset({e['source_id'] for e in evidence}))
        locations={(e['source_id'],e.get('pdf_page')) for e in evidence}
        self.assertTrue(all((m['source_id'],c['pdf_page']) in locations for m in metrics for c in m['calculations'].values()))
        self.assertLessEqual(len(evidence),24)

class AnnouncementTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=core.DATA)
        self.assertTrue(Path(self.folder.name).resolve().is_relative_to(core.DATA.resolve()))
        self.patch=patch.object(a,'DB',Path(self.folder.name)/'updates.sqlite3');self.patch.start()
    def tearDown(self):self.patch.stop();self.folder.cleanup()
    def raw(self,aid='1225588522',date='2026-09-30',code='000333'):
        stamp=int(dt.datetime.fromisoformat(date).replace(tzinfo=a.TZ).timestamp()*1000)
        return {'secCode':code,'announcementId':aid,'announcementTitle':'<em>美的集团</em>：公告',
                'announcementTime':stamp,'adjunctUrl':f'finalpage/{date}/{aid}.PDF'}

    def test_official_date_uses_beijing_timezone(self):
        c=a.normalize('000333',self.raw(),'cninfo');self.assertEqual(c['publication_date'],'2026-09-30')
        self.assertEqual(c['title'],'美的集团：公告');self.assertFalse(c['date_conflict'])
        self.assertIsNone(a.normalize('000333',self.raw(code='000651'),'cninfo'))
        raw=self.raw();raw['adjunctUrl']='https://localhost/private.pdf';self.assertIsNone(a.normalize('000333',raw,'cninfo'))

    def test_sse_date_and_financial_period_are_not_guessed_from_any_report(self):
        c=a.normalize('600690',{'SECURITY_CODE':'600690','TITLE':'海尔智家股份有限公司2026年半年度报告','SSEDATE':'2026-08-29','URL':'/disclosure/listedinfo/announcement/c/new/2026-08-29/test.pdf'},'sse')
        self.assertEqual(c['period'],'2026-H1')
        self.assertTrue(c['url'].startswith('https://static.sse.com.cn/'))
        self.assertEqual(a.report_period('2025年度内部控制评价报告'),'')
        self.assertEqual(a.report_period('2025年年度报告摘要'),'')
        self.assertEqual(a.report_period('关于参加2026年广东辖区上市公司半年度报告业绩说明会活动的公告'),'')
        self.assertEqual(a.report_period('关于披露2026年半年度报告的提示性公告'),'')

    def test_discovery_deduplicates_pages_and_does_not_accept_out_of_range_or_other_company(self):
        pages=[([self.raw(),self.raw('OTHER',code='000651'),self.raw('OLD','2025-01-01')],2,True,'cninfo',{}),
               ([self.raw(),self.raw('NEW','2026-09-29')],2,False,'cninfo',{})]
        with patch.object(a,'fetch_page',side_effect=pages),patch.object(a,'decorate',side_effect=lambda c:c):
            r=a.discover({'code':'000333','start':'2026-09-01','end':'2026-10-06'})
        self.assertEqual(r['count'],2);self.assertTrue(r['complete'])
        with a.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM candidates').fetchone()[0],2)

    def test_pagination_limit_and_external_failure_are_explicit(self):
        with patch.object(a,'fetch_page',side_effect=lambda code,start,end,key,page:([self.raw(str(page))],999,True,'cninfo',{})),patch.object(a,'decorate',side_effect=lambda c:c):
            r=a.discover({'code':'000333','start':'2026-09-01','end':'2026-10-06'})
        self.assertEqual(r['count'],a.MAX_PAGES);self.assertFalse(r['complete']);self.assertIn('上限',r['companies'][0]['note'])
        with patch.object(a,'fetch_page',side_effect=ValueError('暂时不可用')):
            r=a.discover({'code':'000333','start':'2026-09-01','end':'2026-10-06'})
        self.assertFalse(r['complete']);self.assertEqual(r['count'],0);self.assertIn('不可用',r['companies'][0]['error'])

    def test_import_uses_saved_official_metadata_and_handles_partial_failure(self):
        c=a.normalize('000333',self.raw(),'cninfo');c.update(query_endpoint=a.CNINFO,discovered_at=core.now())
        with a.connect() as db:db.execute('INSERT INTO candidates VALUES (?,?,?,?,?)',(c['id'],core.json_dump(c),'x','x',None))
        with patch.object(a,'decorate',side_effect=lambda c:dict(c,status='new')),patch.object(knowledge,'import_document',return_value={'source_id':'CUSTOM_test','duplicate':False}) as ingest:
            r=a.import_selected({'ids':[c['id']], 'url':'https://attacker.invalid/override'})
        self.assertEqual(r['succeeded'],1);self.assertEqual(ingest.call_args.args[0]['url'],c['url'])
        self.assertEqual(ingest.call_args.kwargs['verified_metadata']['announcement_id'],c['announcement_id'])
        with patch.object(a,'decorate',side_effect=lambda c:dict(c,status='new')),patch.object(knowledge,'import_document',side_effect=ValueError('扫描资料')):
            r=a.import_selected({'ids':[c['id']]})
        self.assertEqual(r['failed'],1);self.assertEqual(r['data'][0]['error'],'扫描资料')

    def test_title_dedup_and_paused_documents_are_distinguished(self):
        c=a.normalize('000333',self.raw(),'cninfo')
        known=[{'source_id':'KNOWN','stock_code':'000333','title':'公告','publication_date':'2026-09-30','enabled':False}]
        self.assertEqual(a.decorate(c,known)['status'],'paused')
        known[0]['enabled']=True;self.assertEqual(a.decorate(c,known)['status'],'available')
        known[0]['publication_date']='2026-09-29';self.assertEqual(a.decorate(c,known)['status'],'new')

    def test_invalid_dates_range_and_batch_limits_fail_before_network(self):
        for body in [{'start':'2025-01-01','end':'2026-10-06'}, {'start':'2026-09-01','end':'2099-01-01'},{'start':'bad'},{'start':'2026-10-06','end':'2026-09-01'}]:
            with self.assertRaises(ValueError):a.discover(body)
        with self.assertRaises(ValueError):a.import_selected({'ids':['x']*6})

    def test_compressed_official_pdf_is_decoded_before_indexing(self):
        raw=b'%PDF-1.7\npublic source bytes';response=io.BytesIO(gzip.compress(raw));response.headers={'Content-Type':'application/pdf'}
        with patch.object(knowledge,'allowed_url'),patch.object(knowledge.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=response
            got,suffix=knowledge.fetch_document('https://static.sse.com.cn/test.pdf')
        self.assertEqual(got,raw);self.assertEqual(suffix,'pdf')

    def test_access_challenge_is_never_saved_as_a_pdf_source(self):
        response=io.BytesIO(gzip.compress(b'<html><script>access challenge</script></html>'));response.headers={'Content-Type':'text/html'}
        with patch.object(knowledge,'allowed_url'),patch.object(knowledge.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=response
            with self.assertRaisesRegex(ValueError,'没有返回PDF原件'):knowledge.fetch_document('https://static.sse.com.cn/test.pdf')

    def test_alternate_official_copy_requires_exact_company_date_and_title(self):
        c={'code':'600690','publication_date':'2026-09-30','title':'海尔智家股份有限公司关于提供担保的公告'}
        raw=self.raw(code='600690');raw['announcementTitle']=c['title']
        with patch.object(a,'request_json',return_value={'announcements':[raw]}):
            mirror,proof=a.verified_mirror(c)
        self.assertEqual(mirror['publication_date'],c['publication_date']);self.assertEqual(proof['provider'],'cninfo')
        raw['announcementTime']+=24*60*60*1000
        with patch.object(a,'request_json',return_value={'announcements':[raw]}):
            with self.assertRaisesRegex(ValueError,'唯一同日同名'):a.verified_mirror(c)

def model_module():return retrieval.model

if __name__=='__main__':unittest.main()
