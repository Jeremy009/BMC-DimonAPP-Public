"""Fictional activities for the screenshots, added on top of `make seed`.

Every activity goes through the real submission gate with the fake Dimona service. Each one is
submitted as if on its own date, since workers may only declare from today on.
"""

import logging
from datetime import time, timedelta
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa

from dimonapp.clock import read_today
from dimonapp.database import create_database_engine, open_session
from dimonapp.dimona import FakeDimonaClient
from dimonapp.models import Worker
from dimonapp.settings import load_settings
from dimonapp.submission import ActivityForm, submit_activity

logger = logging.getLogger(__name__)

# Username, days before today, activity type, hours, start time (flexi-job only), supplement,
# description
DEMO_ACTIVITIES: list[tuple[str, int, str, str, Optional[time], bool, str]] = [
    ('camille', 40, 'permanence', '4', None, False, 'Accueil du samedi'),
    ('camille', 26, 'courses', '2', None, False, 'Cours enfants'),
    ('camille', 12, 'permanence', '3', None, False, 'Accueil du mercredi'),
    ('camille', 5, 'route_cleaning_easy', '2', None, False, 'Nettoyage secteur dalle'),
    ('noor', 33, 'group_with_instructor', '3', None, True, 'Groupe scolaire'),
    ('noor', 19, 'courses', '2', None, False, 'Cours adultes débutants'),
    ('noor', 9, 'route_setting_medium', '4', None, True, 'Six voies au dévers'),
    ('noor', 2, 'group_without_instructor', '2', None, False, 'Anniversaire'),
    ('sam', 21, 'permanence', '5', None, False, 'Accueil du dimanche'),
    ('sam', 7, 'route_setting_hard', '3', None, False, 'Bloc compétition'),
    ('robin', 28, 'permanence', '4', time(17, 0), False, 'Accueil du soir'),
    ('robin', 14, 'permanence', '3', time(18, 0), False, 'Accueil du soir'),
    ('robin', 3, 'courses', '3', time(10, 0), False, "Stage d'automne"),
    ('alex', 24, 'route_setting_easy', '6', None, False, 'Quatre voies initiation'),
    ('alex', 6, 'route_setting_medium', '5', None, False, 'Cinq voies secteur nord'),
]


def main() -> None:
    """Submit the demo activities to the local database; never in production."""
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    if settings.app_env == 'PROD':
        raise SystemExit('Demo activities are never added in production.')

    engine = create_database_engine(database_url=settings.database_url)
    dimona_client = FakeDimonaClient()
    today = read_today()
    with open_session(engine=engine) as session:
        workers = session.scalars(sa.select(Worker)).all()
        worker_ids = {worker.username: worker.id for worker in workers}
        for (
            username,
            days_ago,
            activity_type,
            hours,
            start_time,
            with_supplement,
            description,
        ) in DEMO_ACTIVITIES:
            activity_date = today - timedelta(days=days_ago)
            form = ActivityForm(
                activity_date=activity_date,
                activity_type=activity_type,
                duration_hours=Decimal(hours),
                description=description,
                start_time=start_time,
                with_supplement=with_supplement,
            )
            result = submit_activity(
                session=session,
                dimona_client=dimona_client,
                worker_id=worker_ids[username],
                form=form,
                today=activity_date,
            )
            if result.activity_id is None:
                raise SystemExit(f'Demo activity of {username} refused: {result.message}')
    engine.dispose()
    logger.info(f'{len(DEMO_ACTIVITIES)} demo activities added.')


if __name__ == '__main__':
    main()
