"""Worker types, their French labels and the Dimona rule (R5.1, R5.2, R18.4)."""

import pytest

from dimonapp.models import WorkerType
from dimonapp.worker_types import ADMIN_LABEL, WORKER_TYPE_LABELS, requires_dimona


def test_r5_1_exactly_four_worker_types() -> None:
    """The application knows the four worker types of the FDS and no other."""
    worker_types = {worker_type.value for worker_type in WorkerType}

    assert worker_types == {'vrijwilliger', 'article_17', 'flexi_job', 'freelancer'}


@pytest.mark.parametrize(
    ('worker_type', 'expected'),
    [
        (WorkerType.VRIJWILLIGER, False),
        (WorkerType.ARTICLE_17, True),
        (WorkerType.FLEXI_JOB, True),
        (WorkerType.FREELANCER, False),
    ],
)
def test_r5_2_dimona_required_for_article_17_and_flexi_job_only(
    worker_type: WorkerType,
    expected: bool,
) -> None:
    """Only article 17 and flexi-job activities need a Dimona declaration."""
    assert requires_dimona(worker_type=worker_type) is expected


def test_r18_4_account_types_have_their_french_labels() -> None:
    """The sidebar names the account type in French, as listed in FDS 3.4."""
    assert WORKER_TYPE_LABELS == {
        WorkerType.VRIJWILLIGER: 'Volontaire',
        WorkerType.ARTICLE_17: 'Article 17',
        WorkerType.FLEXI_JOB: 'Flexijob',
        WorkerType.FREELANCER: 'Indépendant',
    }
    assert ADMIN_LABEL == 'Admin'
