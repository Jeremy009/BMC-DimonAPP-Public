"""Optional check of the real Dimona client against the RSZ test service (R2.3, R8.5, R8.9, R9.3).

Never part of `make test`: pytest does not enter this folder unless it is named on the
command line, and the test is skipped unless RSZ_INTEGRATION=1. Run it with `make test-rsz`,
which runs as the ACC environment,
with the DIMONA_* settings in .env and the national register number of a test worker in
RSZ_TEST_NATIONAL_REGISTER_NUMBER. It declares one article 17 activity for tomorrow and
cancels it again, then does the same for a day with two activities, whose second one raises
the hours of the period. It only runs as ACC, so it can never reach the live service.
"""

import os
from datetime import date, timedelta

import pytest

from dimonapp.dimona import DimonaDeclaration
from dimonapp.models import WorkerType
from dimonapp.rsz_dimona import RSZ_TEST_HOST, RszDimonaClient, build_dimona_client
from dimonapp.settings import load_settings

is_enabled = os.environ.get('RSZ_INTEGRATION') == '1'
pytestmark = pytest.mark.skipif(not is_enabled, reason='Set RSZ_INTEGRATION=1 to call the RSZ.')


def build_test_client() -> RszDimonaClient:
    """Give the client of the RSZ test service, refusing any other environment."""
    settings = load_settings()
    if settings.app_env != 'ACC':
        pytest.fail('Only the ACC environment may declare here: it calls the RSZ test service.')
    client = build_dimona_client(settings=settings)
    assert isinstance(client, RszDimonaClient)
    assert client.config.base_url.startswith(RSZ_TEST_HOST)
    return client


def build_test_declaration(days_ahead: int) -> DimonaDeclaration:
    """Build an article 17 declaration of 2 hours for the test worker, some days ahead."""
    national_register_number = os.environ.get('RSZ_TEST_NATIONAL_REGISTER_NUMBER')
    if not national_register_number:
        pytest.skip('Needs RSZ_TEST_NATIONAL_REGISTER_NUMBER.')
    return DimonaDeclaration(
        national_register_number=national_register_number,
        worker_type=WorkerType.ARTICLE_17,
        activity_date=date.today() + timedelta(days=days_ahead),
        planned_hours=2,
    )


def test_r8_5_r9_3_declare_then_cancel_at_the_rsz_test_service() -> None:
    """A declaration is accepted with a number, and that number can be cancelled."""
    declaration = build_test_declaration(days_ahead=1)
    client = build_test_client()

    declared = client.declare(declaration=declaration)

    assert declared.status == 'accepted', declared.message
    cancelled = client.cancel(declaration_id=declared.declaration_id)
    assert cancelled.status == 'confirmed', cancelled.message


def test_r8_9_r9_6_second_activity_of_the_day_updates_the_period() -> None:
    """A second activity raises the hours, a cancellation lowers them, the last one cancels."""
    declaration = build_test_declaration(days_ahead=2)
    client = build_test_client()

    declared = client.declare(declaration=declaration)

    assert declared.status == 'accepted', declared.message
    first_id = declared.declaration_id
    raised = client.update_hours(declaration_id=first_id, planned_hours=5)
    assert raised.status == 'accepted', raised.message
    lowered = client.update_hours(declaration_id=raised.declaration_id, planned_hours=3)
    assert lowered.status == 'accepted', lowered.message
    cancelled = client.cancel(declaration_id=first_id)
    assert cancelled.status == 'confirmed', cancelled.message
