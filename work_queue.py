import datetime
from uuid import uuid4

import redis


class WorkQueue():
    def __init__(self, redis_connection,
                 tidy_interval=30000,
                 stale_time=30000):
        self.redis = redis_connection
        self.tidy_interval = tidy_interval
        self.stale_time = stale_time
        self.PENDING = "pending"
        self.WORKING = "working"
        self.VALUES = "values"
        self.RESULTS = "results"

    def enqueue(self, job):
        id = uuid4()
        self.redis.hset(self.VALUES, id, job)
        self.redis.lpush(self.PENDING, id)

    def dequeue(self):
        pipeline = self.redis.pipeline()
        id = pipeline.rpop(self.PENDING)
        pipeline.zadd(self.WORKING, id, _timestamp())
        result = pipeline.execute()
        return result[0]

    def value(self, id):
        return self.redis.hget(self.VALUES, id)

    def record(self, id, result):
        self.redis.hmset(self.RESULTS, id, result)

    def _tidy(self):
        pipeline = self.redis.pipeline()
        pipeline.zrangebyscore(
            self.WORKING, 0, _timestamp() - self.stale_time
        )
        pipeline.zremrangebyscore(
            self.WORKING, 0, _timestamp() - self.stale_time
        )
        stale_jobs = pipeline.execute()[0]

        is_completed = self.redis.hexists(self.RESULTS, stale_jobs)
        pipeline = self.redis.pipelin()
        for job, completed in zip(stale_jobs, is_completed):
            if not completed:
                pipeline.lpush(self.PENDING, job)
        pipeline.execute()


def _timestamp():
    return datetime.datetime.now().timestamp()


if __name__ == '__main__':
    r = redis.Redis()
    wq = WorkQueue(r)
    wq.enqueue("test")
    id = wq.dequeue()
    wq.value(id)
