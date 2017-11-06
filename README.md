# Reliable Worker Queue

Here we present a tutorial explaining how to setup a fault tolerant work queue in python, using Redis as a backend.

## Requirements

* Python, version >= 3.5: A relatively recent version of Python 3 is required because the code utilizes modern features of the asyncio library. 
* Redis: install following the provided [instructions](https://redis.io/topics/quickstart). The code assumes that a basic Redis server is up and running on your computer, which comes from running the command
```
redis-server
```
* redis-py: Python library used to interface with Redis. The easiest way to install it is using `pip`:
```
pip install redis
```

## Overview

In distributed computing, it is common to establish a work queue to organize the tasks still to be computed, and to feed them to available workers. However, a traditional queue data structure is not sufficient to ensure fault tolerance.

The problem can be summarized by the following example. Suppose you have a queue of jobs waiting to be completed. If a worker pops the first job off the queue then crashes or otherwise fails to complete the task, the job is lost forever with no record of it in the system.

One solution is to augment the queue with a list of jobs that are currently being processed, sorted by time that the job was pulled off the queue. Periodically, one goes through the list of jobs being worked on and any that are older than a predetermined threshold are placed back on the queue. This type of system seeks to guarantee that every job is processed **at least once**.

## Implementation

[Redis](https://redis.io/) is a scalable, highly performant in-memory database with a straightforward interface available in a number of languages. It is a natural choice for this type of project, especially for a work queue being used in a cloud-based web application, which likely has need of some type of in-memory store for other aspects of the program.

We demonstrate a proof-of-concept construction of a reliable work queue, implemented in python, but it would be a straightforward exercise to port it to any language with a Redis library. We use the following data structures, all of which are supported by Redis:
  * `values`: A [hash map](https://redis.io/topics/data-types#hashes) of the form `(uuid, value)`, where ``uuid`` is a system generated id tag for the job, and `value` is a string describing the job to be done (e.g. a JSON encoded string).
  * `pending`: A [list](https://redis.io/topics/data-types#lists) of UUIDs corresponding to jobs still waiting to be processed.
  * `working`: A [sorted set](https://redis.io/topics/data-types#sorted-sets) of UUISs corresponding to jobs that have been pulled off the queue by a worker module, but not yet completed.
  * `results`: A [hash map](https://redis.io/topics/data-types#hashes) of the form `(uuid, result)`, where `result` is the output from a worker from processing the job identified by `uuid`.

  In the provided code, the python interface to these data structures is provided by the `WorkQueue` class. It implements the methods `enqueue(job)`, `dequeue()`, `record(uuid, result)`, `value(uuid)`, and `schedule_tidy_task()`, each of which are described in more detail below.

  ### Initialization

 ```python
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
 ```

To initialize a `WorkQueue` class, one needs to specify the connection to the Redis backend, and optionally specify `stale_time` and `tidy_interval`, which specify how long to wait before considering a job orphaned by a worker process, and how long to wait between runs of tidying up the queue, respectively. The `PENDING`, `WORKING`, `VALUES`, and `RESULTS` fields give the names of the data structures allocated in the Redis backend. The `tidy_started` and `_task` fields are used to coordinate scheduling the task which keeps the queue tidy, as explained below.

### `enqueue`
The code to add a job to the queue is below.
```python
def enqueue(self, job):
    id = uuid.uuid4()
    self.redis.hset(self.VALUES, id, job)
    self.redis.lpush(self.PENDING, id)
```
First, one needs to generate a unique identifying id to identify the job across the various data structures. We use python's `uuid` library for this purpose. `HSET` is the command to add the hash pair `(id, job)` to the hash map named 'values'. Finally, the `LPUSH` adds the job's uuid to the task queue.

### `dequeue`
To pull the next available job off the queue, we have the following.
```python
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
```
Here we see a few more aspects of Redis that help make the operations more robust. *Pipelines* provide a way for python to implement blocks of transactions that are guaranteed to run on the redis server serially. This is equivalent to including the operations in a `MULTI` ... `EXEC` block on the Redis command line app.  What complicates matters a little, is that we need to access an intermediate value from the transaction (the jobid popped off the stack). This is solved by introducing watch variables, which allow us to process transactions normally, with the entire block failing if another thread modifies the watched variable somewhere in the middle of the block. When this happens, we simply try again. 

The `ZADD` command adds an item to a Redis sorted set, which in this case keeps the added items sorted in order of their timestamps. This allows for easy retrieval of jobs that have been orphaned.  Finally, we return the uuid of the job that the worker is assigned to process.

### Retrieving values and recording output

To retrieve the job and record the output from the worker we have the following helper methods.
```python
def value(self, id):
    return self.redis.hget(self.VALUES, id)

def record(self, id, result):
    self.redis.hset(self.RESULTS, id, result)
```

`value` simply retrieves the stored input from the hash map corresponding to the given uuid. `record` is called by the worker after completing a job to store the output of the job.

### Requeueing stalled jobs

Periodically, the work queue needs to run the following helper method, with frequency determined by the `tidy_interval` field determined at initialization.
```python
def _tidy(self):
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
```
Here we again utilize a pipeline to keep the entire transaction atomic. We first grab all the in-progress jobs that are older than `stale_time`, and remove them from the `working` set. We check these jobs to see if they have output results recorded for them (indicating that the worker successfully completed the job). Any not completed are put back on the `pending` queue to be processed again.

Note that in order to periodically call this method without blocking the entire program, we need to utilize python's [asyncio library](https://docs.python.org/3/library/asyncio.html). This is a complex subject, and not particularly relevant for the topic at hand, so we omit a detailed explanation of how this works. However, full working source code can be viewed on the [github page](https://github.com/safnuk/reliable-worker-queue/blob/master/work_queue.py).

## Testing the work queue

A small test program can be found in [test_queue.py](https://github.com/safnuk/reliable-worker-queue/blob/master/test_queue.py). This sets up a producer which adds jobs to the queue on a regular basis. Each job is of the form "Job n", where n is a counter for the number of jobs added to date. It also sets up two worker processes who grab a job and prepend their name to the string. Each worker consumes at a different rate and periodically fails so that you can get a sense of how the work queue operates. It will run for 60 seconds, then close the threads and exit.

Run the test cases using the command
```
python3 test_queue.py
```
You should see results similar to the following.
```
Start
Good Worker:b'Job 0'
Good Worker:b'Job 1'
Good Worker:None
Good Worker:b'Job 3'
Tidying up
Bad Worker:b'Job 4'
Good Worker:b'Job 5'
Good Worker:b'Job 6'
Bad Worker:b'Job 8'
Good Worker:b'Job 10'
Tidying up
Job b'991058fe-9f10-4ec3-863a-171d9a2df183' failed
Good Worker:b'Job 12'
Good Worker:b'Job 2'
Good Worker:b'Job 13'
Bad Worker:b'Job 14'
.
.  [Intermediate output omitted]
.
Stopping tidy task
```

The complete codebase can be accessed on [github](https://github.com/safnuk/reliable-worker-queue).
