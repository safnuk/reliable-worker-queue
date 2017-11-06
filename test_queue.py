import asyncio
from contextlib import suppress
import random

import redis

from work_queue import WorkQueue


class Periodic:
    def __init__(self, work_queue=None, delay=1):
        self.queue = work_queue
        self.delay = delay
        self.is_started = False
        self._task = None

    async def start(self):
        if not self.is_started:
            self.is_started = True
            self._task = asyncio.ensure_future(self._run())
        pass

    async def stop(self):
        if self.is_started:
            self.is_started = False
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self):
        while True:
            await asyncio.sleep(self.delay)
            self._do_work()

    def _do_work(self):
        print("Implement me!")


class Worker(Periodic):
    def __init__(self, name, fail_rate=0, **kwargs):
        super().__init__(**kwargs)
        self.fail_rate = fail_rate
        self.name = name

    def _do_work(self):
        jobid = self.queue.dequeue()
        if random.random() < self.fail_rate:
            return
        job = self.queue.value(jobid)
        result = "{}:{}".format(self.name, job)
        print(result)
        self.queue.record(jobid, result)


class Producer(Periodic):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.counter = 0

    def _do_work(self):
        self.queue.enqueue("Job {}".format(self.counter))
        self.counter += 1


async def main():
    r = redis.Redis()
    wq = WorkQueue(r, tidy_interval=5, stale_time=3)
    prod = Producer(work_queue=wq, delay=0.75)
    worker = Worker("Good Worker", work_queue=wq, delay=1, fail_rate=0.2)
    bad_worker = Worker("Bad Worker", work_queue=wq, delay=2.5, fail_rate=0.7)
    try:
        print('Start')
        await wq.schedule_tidy_task()
        await prod.start()
        await worker.start()
        await bad_worker.start()
        await asyncio.sleep(61)
    finally:
        await wq.stop_tidy_task()
        await prod.stop()
        await worker.stop()
        await bad_worker.stop()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
