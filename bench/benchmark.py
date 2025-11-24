import asyncio
import time
import json
import os

from isocode.utils.isoutils import dbutils

# Configure these values
CONCURRENCY = int(os.environ.get("BENCH_CONCURRENCY", "50"))
ITERATIONS = int(os.environ.get("BENCH_ITERATIONS", "20"))
TEST_USER_ID = int(os.environ.get("BENCH_USER_ID", "12345"))

async def simulated_callback(user_id: int):
    # Simulate handler work: fetch user once, build settings, do a couple of reads
    user = await dbutils.get_or_create_user(user_id)
    settings = await dbutils.get_user_settings(user)
    # simulate a couple of getter calls that would otherwise do DB reads
    _ = await dbutils.get_video_codec(user_id, user=user)
    _ = await dbutils.get_resolution(user_id, user=user)
    return True

async def worker(worker_id: int, user_id: int, iters: int):
    for i in range(iters):
        await simulated_callback(user_id)

async def run_benchmark():
    reset = getattr(dbutils, 'reset_db_access_count', None)
    getcount = getattr(dbutils, 'get_db_access_count', None)
    if reset:
        reset()

    start = time.time()
    tasks = []
    per_worker = max(1, ITERATIONS)
    for i in range(CONCURRENCY):
        tasks.append(asyncio.create_task(worker(i, TEST_USER_ID, per_worker)))

    await asyncio.gather(*tasks)
    end = time.time()

    total_time = end - start
    db_accesses = getcount() if getcount else -1

    result = {
        'concurrency': CONCURRENCY,
        'iterations': ITERATIONS,
        'total_time_s': total_time,
        'db_access_count': db_accesses,
        'time_per_op_ms': (total_time / (CONCURRENCY * ITERATIONS)) * 1000
    }

    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    asyncio.run(run_benchmark())
