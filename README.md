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

The problem can be summarized by the following example. Suppose you have a queue of jobs waiting to be completed. If a worker pops the first job off the queue then goes down while processing it, the job is lost forever with no record of it in the system.

One solution is to augment the queue with a list of jobs that are currently being processed, sorted by time that the job was pulled off the queue. Periodically, one goes through the list of jobs being worked on and any that are older than a predetermined threshold are placed back on the queue. This type of system seeks to guarantee that every job is processed at least once.
