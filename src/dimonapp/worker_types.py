"""Rules that depend on the worker type (FDS section 5).

The one-way ladder of FDS 5.1 (vrijwilliger, then article 17, then flexi-job, with freelancer
outside it) is a rule the admin applies when changing a worker's type. It is documented here
and in the FDS, and deliberately not enforced in code (R5.3, R5.4).
"""

from dimonapp.models import Worker, WorkerType

DIMONA_WORKER_TYPES = (WorkerType.ARTICLE_17, WorkerType.FLEXI_JOB)

# French names of the account types, as shown in the interface (FDS 3.4).
WORKER_TYPE_LABELS = {
    WorkerType.VRIJWILLIGER: 'Volontaire',
    WorkerType.ARTICLE_17: 'Article 17',
    WorkerType.FLEXI_JOB: 'Flexijob',
    WorkerType.FREELANCER: 'Indépendant',
}
ADMIN_LABEL = 'Admin'


def requires_dimona(worker_type: WorkerType) -> bool:
    """Tell whether activities of this worker type need a Dimona declaration (R5.2)."""
    return worker_type in DIMONA_WORKER_TYPES


def build_worker_name(worker: Worker) -> str:
    """Give the full name of a worker, first name first."""
    return f'{worker.first_name} {worker.last_name}'


def build_worker_option(worker: Worker) -> str:
    """Name a worker in a list of workers, for example Lotte Peeters (Article 17)."""
    name = build_worker_name(worker=worker)
    type_label = WORKER_TYPE_LABELS[worker.worker_type]
    return f'{name} ({type_label})'
