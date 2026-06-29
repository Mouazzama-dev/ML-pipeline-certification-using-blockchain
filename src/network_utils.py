import time

import requests

# Exceptions that indicate a transient network failure worth retrying.
# RuntimeError from the SDK means a business-logic failure (bad key, wrong
# account, etc.) — those are not retried.
_RETRYABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ReadTimeout,
    requests.exceptions.ChunkedEncodingError,
    OSError,
    TimeoutError,
)


def call_with_retry(fn, *args, max_attempts: int = 3, backoff_base: float = 2.0, **kwargs):
    """
    Call fn(*args, **kwargs), retrying on transient network errors.

    Retries up to max_attempts times with exponential backoff (1 s, 2 s, 4 s …).
    Non-network exceptions (RuntimeError, ValueError, …) propagate immediately.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except _RETRYABLE as exc:
            if attempt == max_attempts:
                raise
            delay = backoff_base ** (attempt - 1)
            print(
                f"Network error (attempt {attempt}/{max_attempts}): {exc}. "
                f"Retrying in {delay:.0f}s..."
            )
            time.sleep(delay)
