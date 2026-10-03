"""HTTP and queue failures use an explicit test-only in-memory store."""
import asyncio
import copy
import unittest
from fastapi.testclient import TestClient
from travel_agent.agent import evaluate_claims
from travel_agent.api import create_app
from travel_agent.core import SAMPLE_CLAIMS
from travel_agent.schemas import EvaluationRequest
from travel_agent.service import EvaluationService, QueueFullError


class MemoryStore:
    def __init__(self):
        self.results, self.saved_jobs = {}, {}
    async def open(self, claims):
        for job in self.saved_jobs.values():
            if job['status'] in {'queued', 'running'}:
                job.update(status='failed', error='Server restarted before this job completed.')
    async def latest(self): return copy.deepcopy(self.results)
    async def jobs(self): return copy.deepcopy(list(self.saved_jobs.values()))
    async def save_job(self, job): self.saved_jobs[job['job_id']] = copy.deepcopy(job)
    async def save_evaluation(self, envelope, job=None):
        self.results[envelope['claim']['claim_id']] = copy.deepcopy(envelope)
        if job: await self.save_job(job)
    async def close(self): pass


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(lambda: EvaluationService(store=MemoryStore(), claims=SAMPLE_CLAIMS))
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()
    def tearDown(self): self.context.__exit__(None, None, None)

    def test_snapshot_is_exact_and_numeric(self):
        response = self.client.get('/api/v1/evaluations/latest')
        self.assertEqual(response.status_code, 200)
        rows = response.json()['evaluations']
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[2]['result']['approved_amount'], 840)
        self.assertEqual(len(rows[0]['result']), 9)
        self.assertIn('X-Request-ID', response.headers)
        self.assertIn('Server-Timing', response.headers)

    def test_policy_and_new_dataset(self):
        policies = self.client.get('/api/v1/policies').json()
        self.assertEqual(len(policies['rules']), 12)
        self.assertEqual(len(policies['tools']), 6)
        rows = self.client.get('/api/v1/sample-claims').json()['claims']
        self.assertEqual(len(rows), 28)
        self.assertTrue(all(row['claim_id'].startswith('DEMO-') for row in rows))

    def test_validation_unknown_and_duplicate_ids(self):
        for body in ({'mode':'invented'}, {'claim_ids':[]}, {'claim_ids':['CLM-001','CLM-001']}, {'unknown':'x'},
                     {'claim_ids':['CLM-001'], 'claims':[SAMPLE_CLAIMS[0]]}):
            self.assertEqual(self.client.post('/api/v1/evaluations', json=body).status_code, 422)
        self.assertEqual(self.client.post('/api/v1/evaluations', json={'claim_ids':['missing']}).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/evaluations/missing').status_code, 404)

    def test_job_reexecutes_real_mcp(self):
        response = self.client.post('/api/v1/evaluations', json={'claim_ids':['CLM-003'], 'mode':'replay'})
        self.assertEqual(response.status_code, 202)
        job_id = response.json()['job_id']
        import time
        for _ in range(100):
            job = self.client.get(f'/api/v1/evaluations/{job_id}').json()
            if job['status'] in {'completed','failed'}: break
            time.sleep(.01)
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['evaluations'][0]['result']['approved_amount'], 840)
        self.assertEqual(len(job['evaluations'][0]['audit']['events']), 6)

    def test_modified_sample_cannot_overwrite_seed(self):
        raw = copy.deepcopy(SAMPLE_CLAIMS[0]); raw['purpose'] = 'Changed synthetic purpose'
        response = self.client.post('/api/v1/evaluations', json={'claims':[raw]})
        self.assertEqual(response.status_code, 422)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = MemoryStore()
        self.service = EvaluationService(store=self.store, claims=SAMPLE_CLAIMS, queue_limit=1)
        await self.service.start()
        await self.service.close()
        self.service.worker = None
    async def asyncTearDown(self): await self.service.close()

    async def test_duplicate_submissions_share_job_and_queue_is_bounded(self):
        request = EvaluationRequest(claim_ids=['CLM-001'], mode='replay')
        jobs = await asyncio.gather(self.service.submit(request), self.service.submit(request))
        self.assertEqual(jobs[0].job_id, jobs[1].job_id)
        with self.assertRaises(QueueFullError):
            await self.service.submit(EvaluationRequest(claim_ids=['CLM-002']))

    async def test_unexpected_runner_failure_preserves_results(self):
        before = self.service.snapshot().model_dump()
        async def broken(*args, **kwargs): raise RuntimeError('Controlled failure')
        self.service.runner = broken
        job = await self.service.submit(EvaluationRequest(claim_ids=['CLM-001']))
        self.service.worker = asyncio.create_task(self.service._consume())
        await asyncio.wait_for(self.service.queue.join(), 2)
        self.assertEqual(self.service.get_job(job.job_id).status, 'failed')
        self.assertEqual(self.service.snapshot().model_dump(), before)

    async def test_failed_persistence_never_publishes_new_results(self):
        before = self.service.snapshot().model_dump()
        async def broken(*args, **kwargs): raise RuntimeError('Controlled database write failure')
        self.store.save_evaluation = broken
        job = await self.service.submit(EvaluationRequest(claim_ids=['CLM-003']))
        self.service.worker = asyncio.create_task(self.service._consume())
        await asyncio.wait_for(self.service.queue.join(), 2)
        self.assertEqual(self.service.get_job(job.job_id).status, 'failed')
        self.assertEqual(self.service.snapshot().model_dump(), before)

    async def test_wrong_returned_claim_is_not_published(self):
        before = self.service.snapshot().model_dump()
        async def wrong(*args, **kwargs):
            return await evaluate_claims([SAMPLE_CLAIMS[1]], recordings=self.service.recordings)
        self.service.runner = wrong
        job = await self.service.submit(EvaluationRequest(claim_ids=['CLM-001']))
        self.service.worker = asyncio.create_task(self.service._consume())
        await asyncio.wait_for(self.service.queue.join(), 2)
        self.assertEqual(self.service.get_job(job.job_id).status, 'failed')
        self.assertEqual(self.service.snapshot().model_dump(), before)
