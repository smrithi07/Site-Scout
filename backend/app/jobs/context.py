from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class StepContext:
    """What a step function receives. `db` is the step's own transaction: everything the step
    writes commits together with the step being marked done, or not at all."""
    job_id: int
    payload: dict
    outputs: dict[str, dict]  # outputs of the steps already done, by step name
    attempt: int              # this step's attempt number, 1-based
    db: Session


# A step returns a JSON-serialisable dict (its persisted output) or None.
Step = Callable[[StepContext], dict | None]
