"""Decision Workspace: org-owned decisions grounded in uploaded and pasted sources.

A workspace decision is a ``DecisionPlan`` plus rows in ``plans.db``: the
decision itself (``workspace_decisions``), its sources (``decision_sources``,
labelled ``S1``, ``S2``, ... in intake order) and the passages each source is
split into (``decision_passages``, labelled ``S1:P1``, ...). Every row carries
the owning org; reads always filter on it.
"""

from __future__ import annotations
