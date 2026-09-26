"""Running several database transactions at the same moment, with bounded waits.

A barrier releases every worker at once; the join is bounded so a stuck lock fails the test with a
diagnostic instead of hanging the suite forever.
"""
import threading

DEFAULT_TIMEOUT = 20.0


def run_at_once(n: int, work, timeout: float = DEFAULT_TIMEOUT) -> list:
    """Run work(i) in n threads released together; return each result or the exception it raised.

    `work` is called with the worker index. Threads that are still alive after `timeout` are reported as
    a TimeoutError result so the assertion message shows which attempt never finished.
    """
    start = threading.Barrier(n, timeout=timeout)
    results: list = [None] * n

    def worker(i):
        try:
            start.wait()
        except threading.BrokenBarrierError as error:
            results[i] = error
            return
        try:
            results[i] = work(i)
        except Exception as error:                      # noqa: BLE001 - reported, not swallowed
            results[i] = error

    threads = [threading.Thread(target=worker, args=(i,), name=f"worker-{i}") for i in range(n)]
    for thread in threads:
        thread.start()
    for i, thread in enumerate(threads):
        thread.join(timeout)
        if thread.is_alive() and results[i] is None:
            results[i] = TimeoutError(f"worker {i} still running after {timeout}s (lock wait?)")
    return results


def constraint_of(result) -> str | None:
    """The constraint name of an integrity error, else None."""
    return getattr(getattr(result, "diag", None), "constraint_name", None)
