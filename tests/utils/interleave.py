"""Deterministic interleaving of two threads that read, check, then write a dict."""

import threading


class PausingDict(dict):
    """The first ``get`` waits after reading; writes record ``value["org_id"]``."""

    def __init__(self):
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()
        self.writes = []

    def get(self, key, default=None):
        value = super().get(key, default)
        if not self.entered.is_set():
            self.entered.set()
            self.release.wait(timeout=5)
        return value

    def __setitem__(self, key, value):
        self.writes.append(value.get("org_id"))
        super().__setitem__(key, value)


def race(racy, write, first, second):
    """Run ``write(second)`` while ``write(first)`` is paused after its first read."""
    results = {}
    threads = [
        threading.Thread(target=lambda o=o: results.update({o: write(o)})) for o in (first, second)
    ]
    threads[0].start()
    assert racy.entered.wait(timeout=5)
    threads[1].start()
    threads[1].join(timeout=0.5)
    racy.release.set()
    for thread in threads:
        thread.join(timeout=5)
    assert not any(thread.is_alive() for thread in threads)
    return results
