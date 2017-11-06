# Reliable Worker Queue

Here we present a tutorial explaining how to setup a fault tolerant work queue in python, using Redis as a backend.

## Requirements

* Python: tested with 3.6, but should work well with other versions. 
* Redis: install following the provided [instructions](https://redis.io/topics/quickstart). The code assumes that a basic Redis server is up and running on your computer, which comes from running the command
```
redis-server
```

## Overview

In distributed computing, it is common to establish a work queue to organize the tasks still to be computed, and to feed them to available workers. However, a traditional queue data structure is not sufficient to ensure fault tolerance.

The problem can be summarized by the following example. Suppose you have a queue of jobs waiting to be completed. If a worker pops the first job off the queue then crashes or otherwise fails to complete the task, the job is lost forever with no record of it in the system.

One solution is to augment the queue with a list of jobs that are currently being processed, sorted by time that the job was pulled off the queue. Periodically, one goes through the list of jobs being worked on and any that are older than a predetermined threshold are placed back on the queue. This type of system seeks to guarantee that every job is processed **at least once**.

## Implementation

[Redis](https://redis.io/) is a scalable, highly performant in-memory database with a straightforward interface available in a number of languages. It is a natural choice for this type of project, especially for a work queue being used in a cloud-based web application, which likely has need of some type of in-memory store for other aspects of the program.

We demonstrate a proof-of-concept construction of a reliable work queue, implemented in python, but it would be a straightforward exercise to port it to any language with a Redis library. We use the following data structures, all of which are supported by Redis:
  * `Values`: A [hash map](https://redis.io/topics/data-types#hashes) of the form `(uuid, value)`, where ``uuid`` is a system generated id tag for the job, and `value` is a string describing the job to be done (e.g. a JSON encoded string).
  * `Pending`: A [list](https://redis.io/topics/data-types#lists) of UUIDs corresponding to jobs still waiting to be processed.
  * `Working`: A [sorted set](https://redis.io/topics/data-types#sorted-sets) of UUISs corresponding to jobs that have been pulled off the queue by a worker module, but not yet completed.
  * `Results`: A [hash map](https://redis.io/topics/data-types#hashes) of the form `(uuid, result)`, where `result` is the output from a worker from processing the job identified by `uuid`.

  In the provided code, the python interface to these data structures is provided by the `WorkQueue` class. It implements the methods `enqueue(job)`, `dequeue()`, `record(uuid, result)`, and `value(uuid)`, each of which are described in more detail below.

  ### Initialization

 ```python
class WorkQueue():
    def __init__(self, redis_connection,
                 tidy_interval=30,
                 stale_time=30):
        self.redis = redis_connection
        self.tidy_interval = tidy_interval
        self.stale_time = stale_time
        self.PENDING = "pending"
        self.WORKING = "working"
        self.VALUES = "values"
        self.RESULTS = "results"
 ```

To initialize a `WorkQueue` class, one needs to specify the connection to the Redis backend, and optionally specify `stale_time` and `tidy_interval`, which specify how long to wait before considering a job orphaned by a worker process, and how long to wait between runs of tidying up the queue, respectively.


