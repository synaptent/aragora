"""Run the ODR vector corpus in a lane that pull requests actually execute.

The suite itself lives in ``tests/verify/test_odr_vectors.py``, the path the
receipt-first scoreboard measures. Nothing runs that directory on a pull
request: the light shards in ``.github/workflows/test.yml`` enumerate explicit
paths and the baseline job only collects ``tests/``. Re-exporting the suite
here puts it in the ``infra`` shard, so the oracles are checked whenever
``aragora/gauntlet/**`` or ``tests/gauntlet/**`` changes, which is the
regression they exist to catch. Adding ``tests/verify`` to the workflow
instead would be a Tier-4 change.
"""

from tests.verify.test_odr_vectors import *  # noqa: F401,F403
