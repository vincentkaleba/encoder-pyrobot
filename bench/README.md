Benchmark harness

This simple benchmark simulates concurrent callbacks calling the common hot-paths (fetch user, build settings, a couple of getters).

Usage (bash):

```bash
# from repository root
python -m bench.benchmark

# Options via env vars:
# BENCH_CONCURRENCY - number of concurrent workers (default 50)
# BENCH_ITERATIONS  - iterations per worker (default 20)
# BENCH_USER_ID     - user_id to simulate (default 12345)

# Example:
BENCH_CONCURRENCY=100 BENCH_ITERATIONS=50 BENCH_USER_ID=99999 python -m bench.benchmark
```

Notes:
- The harness uses the in-memory DB access counter implemented in `isocode/utils/isoutils/dbutils.py`.
- For realistic numbers run this inside the same environment where the bot runs and where MongoDB is reachable.
