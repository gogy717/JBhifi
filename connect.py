import time

heavy_work = lambda: time.sleep(1)  # 模拟耗时操作

class Timer:
    def __enter__(self):
        self.t = time.time()
        return self              # ← as 拿到的是这个返回值

    def __exit__(self, exc_type, exc_val, exc_tb):
        print(f"耗时 {time.time() - self.t:.2f}s")
        # 返回 None/False → 异常继续往外抛
        # 返回 True       → 异常被吞掉（少用，容易埋雷）

with Timer() as t:
    heavy_work()
    