import asyncio
from contextlib import suppress
import datetime
import uuid

import redis


class WorkQueue():
    def __init__(self, redis_connection,
                 tidy_interval=30,
                 stale_time=30):
        self.redis = redis_connection
        self.tidy_interval = tidy_interval
        self.stale_time = stale_time
        self.tidy_started = False
        self._task = None
        self.PENDING = "pending"
        self.WORKING = "working"
        self.VALUES = "values"
        self.RESULTS = "results"

    def enqueue(self, job):
        id = uuid.uuid4()
        self.redis.hset(self.VALUES, id, job)
        self.redis.lpush(self.PENDING, id)

    def dequeue(self):
        with self.redis.pipeline() as pipeline:
            while 1:
                try:
                    pipeline.watch(self.PENDING)
                    id = pipeline.rpop(self.PENDING)
                    if id is not None:
                        pipeline.zadd(self.WORKING, id, _timestamp())
                    pipeline.execute()
                    break
                except redis.WatchError:
                    continue
        return id

    def value(self, id):
        return self.redis.hget(self.VALUES, id)

    def record(self, id, result):
        self.redis.hset(self.RESULTS, id, result)

    async def schedule_tidy_task(self):
        if not self.tidy_started:
            self.tidy_started = True
            self._task = asyncio.ensure_future(self._run_tidy())

    async def stop_tidy_task(self):
        print('Stopping tidy task')
        if self.tidy_started:
            self.tidy_started = False
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run_tidy(self):
        while True:
            await asyncio.sleep(self.tidy_interval)
            self._tidy()

    def _tidy(self):
        print("Tidying up")
        pipeline = self.redis.pipeline()
        pipeline.zrangebyscore(
            self.WORKING, 0, _timestamp() - self.stale_time
        )
        pipeline.zremrangebyscore(
            self.WORKING, 0, _timestamp() - self.stale_time
        )
        stale_jobs = pipeline.execute()[0]

        if stale_jobs:
            results = self.redis.hmget(self.RESULTS, stale_jobs)
            pipeline = self.redis.pipeline()
            for job, result in zip(stale_jobs, results):
                if result is None:
                    print("Job {} failed".format(job))
                    pipeline.lpush(self.PENDING, job)
            pipeline.execute()


def _timestamp():
    return datetime.datetime.now().timestamp()
