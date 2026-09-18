"""Run the ODR vector corpus in a lane that pull requests actually execute.

The suite itself lives in ``tests/verify/test_odr_vectors.py``, the path the
receipt-first scoreboard measures. Nothing runs that directory on a pull
request: the light shards in ``.github/workflows/test.yml`` enumerate explicit
paths and the baseline job only collects ``tests/``. Re-exporting the suite
here puts all 88 cases in the ``infra`` shard, so they run whenever
``aragora/gauntlet/**`` or another path in that shard's scope changes, and
``bin/gate.sh test`` runs them on every mission gate. It does not cover a pull
request touching only ``tests/verify/**``, ``scripts/gen_odr_vectors.py`` or
``aragora-verify/**``: that pull request still selects no lane that runs the
corpus, because ``.github/workflows/test.yml`` names neither ``tests/verify``
nor ``aragora-verify``. Closing that residual gap is a Tier-4 workflow change,
recorded as an operator-owned follow-up in the mission's parked-and-pending
register, and is not a defect of this corpus.
"""

from tests.verify.test_odr_vectors import *  # noqa: F401,F403
