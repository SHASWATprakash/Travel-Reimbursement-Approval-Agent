"""Actual PostgreSQL integration. Uses a dedicated *_test database only."""
import os
import unittest
from sqlalchemy import select
from travel_agent.agent import evaluate_claims
from travel_agent.core import SAMPLE_CLAIMS
from travel_agent.service import load_recordings
from travel_agent.store import Base, PostgresStore, StoredClaim, StoredEvaluation

URL = os.environ.get('TEST_DATABASE_URL')


@unittest.skipUnless(URL, 'Set TEST_DATABASE_URL to a dedicated PostgreSQL test database')
class PostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not URL.rsplit('/',1)[-1].endswith('_test'):
            raise ValueError('Refusing to reset a database without the _test suffix')
        self.store = PostgresStore(URL)
        async with self.store.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await self.store.open(SAMPLE_CLAIMS)

    async def asyncTearDown(self): await self.store.close()

    async def test_seed_idempotency_and_real_jsonb_storage(self):
        await self.store.open(SAMPLE_CLAIMS)
        async with self.store.sessions() as session:
            rows = (await session.scalars(select(StoredClaim))).all()
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[0].payload['currency'], 'USD')

    async def test_evaluation_survives_reopen_and_money_is_exact(self):
        envelope = (await evaluate_claims([SAMPLE_CLAIMS[2]], recordings=load_recordings()))[0]
        await self.store.save_evaluation(envelope)
        await self.store.close()
        self.store = PostgresStore(URL)
        latest = await self.store.latest()
        self.assertEqual(latest['CLM-003']['result']['approved_amount'], 840)
        self.assertEqual(latest['CLM-003']['result']['deducted_amount'], 100)
        self.assertEqual(len(latest['CLM-003']['audit']['events']), 6)

    async def test_restart_marks_unfinished_jobs_failed(self):
        job = {'job_id':'a'*32,'status':'running','created_at':'2026-10-03T10:00:00+00:00'}
        await self.store.save_job(job)
        await self.store.open(SAMPLE_CLAIMS)
        saved = await self.store.jobs()
        self.assertEqual(saved[0]['status'], 'failed')
        self.assertIn('restarted', saved[0]['error'])

    async def test_job_and_result_are_saved_in_one_transaction(self):
        envelope = (await evaluate_claims([SAMPLE_CLAIMS[0]], recordings=load_recordings()))[0]
        job = {'job_id':'b'*32,'status':'running','created_at':'2026-10-03T10:00:00+00:00','completed_count':1}
        await self.store.save_evaluation(envelope, job)
        saved = await self.store.jobs()
        self.assertEqual(saved[0]['completed_count'], 1)
        async with self.store.sessions() as session:
            row = await session.scalar(select(StoredEvaluation))
            self.assertEqual(row.job_id, job['job_id'])

