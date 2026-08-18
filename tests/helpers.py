import time


def wait_until(
    predicate, timeout: float = 10.0, interval: float = 0.05, message: str = ""
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise TimeoutError(f"condition not met within {timeout}s: {message}")
