"""Offline audit coverage: no service restart, network request or model fees."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

import audit
import core
import model
import research
import server
import questions


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=core.DATA)
        self.addCleanup(self.folder.cleanup)
        self.data_patch = patch.object(core, 'DATA', Path(self.folder.name))
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.cfg = {'provider': 'offline test', 'model': 'requested-alias', 'base_url': 'https://api.example.invalid'}

    def response(self, content='{"ok":true}', finish='stop'):
        return io.BytesIO(json.dumps({'model': 'response-version', 'choices': [{'finish_reason': finish, 'message': {'content': content}}],
                                     'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8, 'private': 'hidden'}}).encode())

    def call(self, response=None, error=None):
        with audit.context(run_id='offline-run'), patch('model.credentials', return_value=(self.cfg, 'test-token')), patch('model.get_config', return_value=self.cfg), patch('urllib.request.urlopen', side_effect=error, return_value=response) as request:
            result = model.complete('sensitive-system-marker', 'sensitive-user-marker')
            self.assertEqual(request.call_count, 1)
            return result

    def test_success_persists_attempt_without_secret_headers_or_prompt(self):
        result, log = self.call(self.response())
        self.assertEqual(result, {'ok': True})
        snapshot = audit.snapshot('offline-run')
        row = snapshot['model_attempts'][0]
        self.assertEqual(row['status'], 'success')
        self.assertEqual(row['model'], 'requested-alias')
        self.assertEqual(row['response_model'], 'response-version')
        self.assertEqual(row['usage']['total_tokens'], 8)
        self.assertEqual(row['attempt_id'], log['attempt_id'])
        text = json.dumps(snapshot)
        for value in ['sensitive-system-marker', 'sensitive-user-marker', 'test-token', 'Authorization', 'hidden']:
            self.assertNotIn(value, text)
        self.assertNotIn('private', row['usage'])

    def test_http_timeout_json_and_length_failures_remain_inspectable(self):
        error = urllib.error.HTTPError('https://api.example.invalid/?secret=do-not-record', 429, 'private-vendor-message', None, io.BytesIO(b'private-vendor-body'))
        cases = [(None, error, 'http_error'), (None, TimeoutError('secret-error-marker'), 'connection_or_timeout'),
                 (self.response('not-json'), None, 'invalid_structured_result'), (self.response('{}', 'length'), None, 'length_limit'),
                 (io.BytesIO(b'bad-response'), None, 'invalid_response_json')]
        for response, failure, kind in cases:
            with self.assertRaises((ValueError, TimeoutError)):
                self.call(response, failure)
            row = audit.snapshot('offline-run')['model_attempts'][-1]
            self.assertEqual(row['status'], 'failed')
            self.assertEqual(row['error_kind'], kind)
        text = json.dumps(audit.snapshot('offline-run'))
        for value in ['private-vendor', 'do-not-record', 'secret-error-marker', 'not-json', 'bad-response']:
            self.assertNotIn(value, text)

    def test_credentials_failure_is_logged_before_network(self):
        with audit.context(run_id='missing-credentials'), patch('model.get_config', return_value=self.cfg), patch('model.credentials', side_effect=ValueError('credentials-not-configured')), patch('urllib.request.urlopen') as request:
            with self.assertRaises(ValueError):
                model.complete('system', 'user')
        request.assert_not_called()
        rows = audit.snapshot('missing-credentials')['model_attempts']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'failed')

    def test_source_read_and_cache_hit_are_different_events(self):
        file = core.DATA/'sample.txt'
        file.write_text('private-document-marker', encoding='utf-8')
        with audit.context(run_id='source-context'):
            self.assertEqual(audit.read_text(file, source_id='PUBLIC_SAMPLE'), 'private-document-marker')
            audit.cache_hit('sample_cache', source_id='PUBLIC_SAMPLE')
            with self.assertRaises(FileNotFoundError):
                audit.read_bytes(core.DATA/'missing.pdf', source_id='MISSING')
        rows = audit.snapshot('source-context')['events']
        self.assertEqual(rows[0]['sha256'], hashlib.sha256(file.read_bytes()).hexdigest())
        self.assertEqual(rows[1]['kind'], 'cache')
        self.assertTrue(rows[1]['cache_hit'])
        self.assertEqual(rows[2]['status'], 'failed')
        self.assertNotIn('private-document-marker', json.dumps(rows))
        self.assertNotIn(str(core.DATA), json.dumps(rows))

    def test_failed_early_research_has_context_and_no_saved_result(self):
        with patch('core.save_run') as save:
            with self.assertRaises(ValueError):
                research.run('invalid-company', '2026-10-06', 'valid research question')
        save.assert_not_called()
        rows = audit.snapshot()['events']
        self.assertEqual([row['status'] for row in rows], ['started', 'failed'])
        self.assertEqual(rows[0]['run_id'], rows[1]['run_id'])

    def test_metadata_whitelist_and_context_ids_cannot_store_body_or_urls(self):
        with audit.context(run_id='https://invalid/?token=secret-marker'):
            audit.event('test', status='success', headers={'Authorization': 'secret-marker'}, body='secret-marker',
                        request_user='secret-marker', relative_source='C:/private/name.txt', provider='Bearer secret-marker')
        text = json.dumps(audit.snapshot())
        self.assertNotIn('secret-marker', text)
        self.assertNotIn('C:/private', text)

    def test_truncation_is_explicit_and_persistent_rows_are_complete(self):
        with audit.context(run_id='many-events'):
            for index in range(4):
                audit.event('test', count=index)
        snapshot = audit.snapshot('many-events', limit=2)
        self.assertTrue(snapshot['truncated'])
        self.assertEqual(snapshot['event_count'], 4)
        self.assertEqual(snapshot['returned_events'], 2)
        self.assertEqual(len(audit.snapshot('many-events')['events']), 4)

    def test_historical_absence_is_not_fabricated(self):
        snapshot = audit.snapshot('historical-no-audit')
        self.assertFalse(snapshot['available'])
        self.assertEqual(snapshot['model_attempts'], [])
        self.assertIn('不追补', snapshot['historical_note'])

    def test_concurrent_contexts_and_attempt_ids_are_separate(self):
        failures = []
        def task(index):
            try:
                with audit.context(run_id='thread-'+str(index)):
                    identity = audit.begin_attempt('test', 'alias', 'system', 'user')
                    audit.finish_attempt(identity, 'success', 1)
            except Exception as error:
                failures.append(type(error).__name__)
        threads = [threading.Thread(target=task, args=(index,)) for index in range(4)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(failures, [])
        attempts = audit.snapshot()['model_attempts']
        self.assertEqual(len({row['attempt_id'] for row in attempts}), 4)
        self.assertEqual({row['run_id'] for row in attempts}, {'thread-'+str(index) for index in range(4)})

    def test_http_range_transfer_digest_is_separate_from_original_digest(self):
        file = core.DATA/'sample.pdf'
        raw = b'0123456789abcdef';file.write_bytes(raw)
        handler = server.Handler.__new__(server.Handler)
        handler.headers = {'Range': 'bytes=2-5'};handler.wfile = io.BytesIO()
        handler.send_response = lambda *args: None
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.reply = lambda *args: None
        original = hashlib.sha256(raw).hexdigest()
        source = {'source_id': 'HTTP_SAMPLE', 'sha256': original}
        with audit.context(run_id='range-access'):
            handler.send_file(file, source=source)
            handler.headers = {'Range': 'bytes=99-100'}
            handler.send_file(file, source=source)
            handler.headers = {}
            handler.send_file(core.DATA/'missing.pdf', source=source)
        rows = audit.snapshot('range-access')['events']
        self.assertEqual(rows[0]['http_status'], 206)
        self.assertEqual(rows[0]['bytes'], 4)
        self.assertEqual(rows[0]['source_sha256'], original)
        self.assertEqual(rows[0]['transfer_sha256'], hashlib.sha256(raw[2:6]).hexdigest())
        self.assertEqual(rows[1]['http_status'], 416)
        self.assertEqual(rows[2]['http_status'], 404)

    def test_report_original_urls_put_audit_query_before_pdf_fragment(self):
        with patch.object(core,'LOCAL_BASE_URL','http://127.0.0.1:8769',create=True):
            url=audit.original_url('SOURCE','parent-run',12)
            self.assertEqual(url,'http://127.0.0.1:8769/api/files/SOURCE?run_id=parent-run#page=12')
            self.assertEqual(audit.original_url('SOURCE',page=12),'http://127.0.0.1:8769/api/files/SOURCE#page=12')

    def test_supplemental_evidence_fallbacks_log_cache_location_and_count(self):
        from unittest.mock import MagicMock
        connection=MagicMock();connection.__enter__.return_value.execute.return_value.fetchall.return_value=[]
        evidence={'source_id':'CUSTOM_SAMPLE','text':'cashflow evidence','pdf_page':3}
        with audit.context(run_id='supplemental-run'),patch('core.connect',return_value=connection),patch('knowledge.passage',return_value=[evidence]):
            self.assertEqual(core.page_evidence('CUSTOM_SAMPLE',3),evidence)
            self.assertEqual(core.source_evidence('CUSTOM_SAMPLE','cashflow',1),[evidence])
        rows=audit.snapshot('supplemental-run')['events']
        self.assertEqual({row['purpose'] for row in rows},{'supplemental_page_text','supplemental_source_text'})
        self.assertTrue(all(row['cache_name']=='knowledge_sqlite_passages' and row['count']==1 and row['source_id']=='CUSTOM_SAMPLE' for row in rows))
        self.assertEqual(rows[0]['page'],3)

    def test_followup_uses_valid_saved_parent_and_invalid_parent_stays_failed(self):
        def answer(body):
            audit.event('test_followup',status='success')
            return {'id':'question-id','run_id':body['run_id']}
        with audit.context(run_id='job-attempt',job_id='followup-job'),patch('core.get_run',return_value={'id':'parent-run'}),patch('questions._answer',side_effect=answer):
            questions.answer({'run_id':'parent-run','question':'valid question'})
            self.assertEqual(audit.current()['run_id'],'job-attempt')
        parent=audit.snapshot('parent-run')
        self.assertTrue(any(row['kind']=='test_followup' and row['job_id']=='followup-job' for row in parent['events']))
        child=audit.snapshot('job-attempt')
        self.assertTrue(any(row.get('parent_run_id')=='parent-run' for row in child['events']))
        with audit.context(run_id='invalid-job',job_id='bad-followup'),patch('core.get_run',side_effect=KeyError('missing-parent')),patch('questions._answer') as answer:
            with self.assertRaises(KeyError):questions.answer({'run_id':'missing-parent','question':'valid question'})
        answer.assert_not_called()
        self.assertTrue(any(row['status']=='failed' for row in audit.snapshot(job_id='bad-followup')['events']))


if __name__ == '__main__':
    unittest.main()
