"""The activity submission gate and the Dimona flow (FDS section 8).

The Dimona service is always the fake (R1.11).
"""

from datetime import date, time, timedelta
from decimal import Decimal
from typing import Optional

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp.dimona import FakeDimonaClient
from dimonapp.fake_data import build_fake_national_register_number
from dimonapp.french import NO_BREAK_SPACE
from dimonapp.models import (
    ACTIVITY_TYPE_CODES,
    RATE_CODES,
    SUPPLEMENT_CODES,
    Activity,
    CompensationModel,
    DimonaStatus,
    DocumentType,
    Period,
    Worker,
    WorkerType,
)
from dimonapp.submission import (
    ActivityForm,
    SubmissionResult,
    find_latest_date,
    submit_activity,
)
from factories import (
    VALID_NATIONAL_REGISTER_NUMBER,
    build_activity,
    build_authorisation,
    build_limit,
    build_rate,
    build_worker,
)

TODAY = date(2026, 10, 10)
START_DATE = date(2026, 1, 1)
SUPPLEMENT_RATE = Decimal('25')
OTHER_NATIONAL_REGISTER_NUMBER = build_fake_national_register_number(
    birth_date=date(1991, 2, 3),
    sequence=123,
)
RATE = Decimal('20')
BOTH_DOCUMENTS = (DocumentType.CONTRACT, DocumentType.QUALIFICATION)


def save_worker(
    session: Session,
    worker_type: WorkerType = WorkerType.ARTICLE_17,
    document_types: tuple[DocumentType, ...] = BOTH_DOCUMENTS,
    is_active: bool = True,
) -> int:
    """Store a worker with every rate and the given documents for every activity type."""
    worker = build_worker(worker_type=worker_type, is_active=is_active)
    session.add(worker)
    session.flush()
    for rate_code in RATE_CODES:
        rate = build_rate(
            valid_from=START_DATE,
            amount=RATE,
            worker_id=worker.id,
            activity_type=rate_code,
        )
        session.add(rate)
    for document_type in document_types:
        authorisation = build_authorisation(
            document_type=document_type,
            activity_types=ACTIVITY_TYPE_CODES,
            start_date=START_DATE,
            worker_id=worker.id,
            worker_type=worker_type,
        )
        session.add(authorisation)
    session.flush()
    return worker.id


def build_form(
    activity_date: Optional[date] = TODAY,
    activity_type: str = 'courses',
    duration_hours: Optional[Decimal] = Decimal('3'),
    description: str = '',
    start_time: Optional[time] = time(hour=17, minute=30),
    with_supplement: bool = False,
) -> ActivityForm:
    """Build a valid create form for an hourly activity today, valid for a flexi-jobber too."""
    return ActivityForm(
        activity_date=activity_date,
        activity_type=activity_type,
        duration_hours=duration_hours,
        description=description,
        start_time=start_time,
        with_supplement=with_supplement,
    )


def submit(
    session: Session,
    worker_id: int,
    form: ActivityForm,
    dimona_client: Optional[FakeDimonaClient] = None,
    today: date = TODAY,
) -> SubmissionResult:
    """Run the gate with an accepting fake Dimona unless another client is given."""
    client = dimona_client or FakeDimonaClient(outcome='accept')
    return submit_activity(
        session=session,
        dimona_client=client,
        worker_id=worker_id,
        form=form,
        today=today,
    )


def count_activities(session: Session) -> int:
    """Count the registered activities."""
    return session.scalar(sa.select(sa.func.count()).select_from(Activity))


def test_r7_4_past_date_is_refused(session: Session) -> None:
    """Yesterday is refused and nothing is registered or declared."""
    worker_id = save_worker(session=session)
    client = FakeDimonaClient(outcome='accept')
    form = build_form(activity_date=TODAY - timedelta(days=1))

    result = submit(session=session, worker_id=worker_id, form=form, dimona_client=client)

    assert result.outcome == 'invalid_input'
    assert result.level == 'error'
    assert result.message == (
        "Activité non enregistrée : la date doit être aujourd'hui ou plus tard."
    )
    assert result.activity_id is None
    assert count_activities(session=session) == 0
    assert client.declarations == []


def test_r7_4_missing_date_is_refused(session: Session) -> None:
    """A form without a date, as the emptied date picker gives it, registers nothing (R8.2)."""
    worker_id = save_worker(session=session)
    client = FakeDimonaClient(outcome='accept')
    form = build_form(activity_date=None)

    result = submit(session=session, worker_id=worker_id, form=form, dimona_client=client)

    assert result.outcome == 'invalid_input'
    assert result.level == 'error'
    assert result.message == "Activité non enregistrée : indiquez la date de l'activité."
    assert result.activity_id is None
    assert count_activities(session=session) == 0
    assert client.declarations == []


def test_r7_4_today_and_later_are_accepted(session: Session) -> None:
    """Today and a future date both pass the date check."""
    worker_id = save_worker(session=session)

    for activity_date in (TODAY, TODAY + timedelta(days=30)):
        form = build_form(activity_date=activity_date)
        result = submit(session=session, worker_id=worker_id, form=form)
        assert result.outcome == 'accepted'


def test_r7_14_three_months_ahead_is_the_latest_date(session: Session) -> None:
    """The same day three months from today still passes."""
    worker_id = save_worker(session=session)
    form = build_form(activity_date=date(2027, 1, 10))

    result = submit(session=session, worker_id=worker_id, form=form)

    assert result.outcome == 'accepted'


def test_r7_14_later_than_three_months_ahead_is_refused(session: Session) -> None:
    """One day further is refused and nothing is registered or declared."""
    worker_id = save_worker(session=session)
    client = FakeDimonaClient(outcome='accept')
    form = build_form(activity_date=date(2027, 1, 11))

    result = submit(session=session, worker_id=worker_id, form=form, dimona_client=client)

    assert result.outcome == 'invalid_input'
    assert result.message == (
        "Activité non enregistrée : une activité se déclare au maximum 3 mois à l'avance."
    )
    assert count_activities(session=session) == 0
    assert client.declarations == []


@pytest.mark.parametrize('duration_hours', [None, Decimal('0')])
def test_r7_5_duration_must_be_entered(session: Session, duration_hours: Optional[Decimal]) -> None:
    """Without a duration nothing is registered, also for a fixed-price activity."""
    worker_id = save_worker(session=session)
    form = build_form(activity_type='permanence', duration_hours=duration_hours)

    result = submit(session=session, worker_id=worker_id, form=form)

    assert result.outcome == 'invalid_input'
    assert result.message == "Activité non enregistrée : indiquez la durée de l'activité en heures."
    assert count_activities(session=session) == 0


def test_r7_5_duration_must_be_whole_hours(session: Session) -> None:
    """A part of an hour is refused: the RSZ only takes whole hours in a declaration."""
    worker_id = save_worker(session=session)
    form = build_form(duration_hours=Decimal('2.5'))

    result = submit(session=session, worker_id=worker_id, form=form)

    assert result.outcome == 'invalid_input'
    assert result.message == 'Activité non enregistrée : la durée se déclare en heures entières.'
    assert count_activities(session=session) == 0


@pytest.mark.parametrize(
    'activity_type',
    ['route_setting_easy', 'route_setting_medium', 'route_setting_hard'],
)
def test_r7_6_route_setting_without_description_is_refused(
    session: Session,
    activity_type: str,
) -> None:
    """The three route setting types need a description; spaces alone do not count."""
    worker_id = save_worker(session=session)
    form = build_form(activity_type=activity_type, description='   ')

    result = submit(session=session, worker_id=worker_id, form=form)

    assert result.outcome == 'invalid_input'
    assert result.message == (
        'Activité non enregistrée : une description courte est obligatoire '
        "pour l'ouverture de voies."
    )
    assert count_activities(session=session) == 0


def test_r7_6_route_setting_with_description_is_registered(session: Session) -> None:
    """With a description the route setting activity passes and the text is stored."""
    worker_id = save_worker(session=session)
    form = build_form(activity_type='route_setting_medium', description=' Secteur B, dévers ')

    result = submit(session=session, worker_id=worker_id, form=form)

    activity = session.get(Activity, result.activity_id)
    assert result.outcome == 'accepted'
    assert activity.description == 'Secteur B, dévers'


@pytest.mark.parametrize(
    'activity_type',
    [
        'permanence',
        'courses',
        'group_without_instructor',
        'group_with_instructor',
        'route_cleaning_easy',
        'route_cleaning_hard',
    ],
)
def test_r7_6_description_is_optional_for_other_types(session: Session, activity_type: str) -> None:
    """Every other activity type is registered without a description."""
    worker_id = save_worker(session=session)
    form = build_form(activity_type=activity_type)

    result = submit(session=session, worker_id=worker_id, form=form)

    activity = session.get(Activity, result.activity_id)
    assert result.outcome == 'accepted'
    assert activity.description is None


def save_flexi_minimum(session: Session, min_hours: Decimal, year: int = TODAY.year) -> None:
    """Configure the minimum hours per flexi-job activity of a year."""
    limit = build_limit(
        year=year,
        worker_type=WorkerType.FLEXI_JOB,
        period=Period.YEAR,
        min_hours_per_activity=min_hours,
    )
    session.add(limit)
    session.flush()


def test_r7_7_flexi_job_below_the_configured_minimum_is_refused(session: Session) -> None:
    """The minimum is read from the yearly limits; a shorter flexi-job activity is refused."""
    worker_id = save_worker(session=session, worker_type=WorkerType.FLEXI_JOB)
    save_flexi_minimum(session=session, min_hours=Decimal('4'))
    form = build_form(duration_hours=Decimal('3'))

    result = submit(session=session, worker_id=worker_id, form=form)

    assert result.outcome == 'invalid_input'
    assert result.message == (
        'Activité non enregistrée : une activité Flexijob dure au minimum 4 h.'
    )
    assert count_activities(session=session) == 0


def test_r7_7_flexi_job_at_the_minimum_is_registered(session: Session) -> None:
    """Exactly the minimum is enough."""
    worker_id = save_worker(session=session, worker_type=WorkerType.FLEXI_JOB)
    save_flexi_minimum(session=session, min_hours=Decimal('3'))
    form = build_form(duration_hours=Decimal('3'))

    result = submit(session=session, worker_id=worker_id, form=form)

    assert result.outcome == 'accepted'


def test_r7_7_minimum_only_applies_to_flexi_jobbers(session: Session) -> None:
    """An article 17 worker may declare a shorter activity."""
    worker_id = save_worker(session=session, worker_type=WorkerType.ARTICLE_17)
    save_flexi_minimum(session=session, min_hours=Decimal('3'))
    form = build_form(duration_hours=Decimal('1'))

    result = submit(session=session, worker_id=worker_id, form=form)

    assert result.outcome == 'accepted'


def test_r7_7_minimum_follows_the_year_of_the_activity(session: Session) -> None:
    """A year without a configured minimum is not guessed from another year and not blocked."""
    worker_id = save_worker(session=session, worker_type=WorkerType.FLEXI_JOB)
    save_flexi_minimum(session=session, min_hours=Decimal('3'), year=TODAY.year)
    december_day = date(TODAY.year, 12, 5)
    next_year_date = date(TODAY.year + 1, 1, 5)
    form = build_form(activity_date=next_year_date, duration_hours=Decimal('1'))

    result = submit(session=session, worker_id=worker_id, form=form, today=december_day)

    assert result.outcome == 'accepted'


def test_r12_1_no_contract_is_refused(session: Session) -> None:
    """Without a contract covering the activity nothing is registered or declared."""
    worker_id = save_worker(session=session, document_types=(DocumentType.QUALIFICATION,))
    client = FakeDimonaClient(outcome='accept')
    form = build_form(activity_type='route_setting_medium', description='Secteur B')

    result = submit(session=session, worker_id=worker_id, form=form, dimona_client=client)

    assert result.outcome == 'no_contract'
    assert result.level == 'error'
    assert result.message == (
        'Activité non enregistrée : aucun contrat Article 17 valide ne couvre '
        "l'ouverture 6A - 6C le 10/10/2026."
    )
    assert count_activities(session=session) == 0
    assert client.declarations == []


def test_r12_1_no_qualification_is_refused(session: Session) -> None:
    """Without a qualification covering the activity nothing is registered or declared."""
    worker_id = save_worker(session=session, document_types=(DocumentType.CONTRACT,))
    client = FakeDimonaClient(outcome='accept')

    result = submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    assert result.outcome == 'no_qualification'
    assert result.level == 'error'
    assert 'aucune qualification valide' in result.message
    assert count_activities(session=session) == 0
    assert client.declarations == []


def test_r12_1_document_must_cover_the_type_and_the_date(session: Session) -> None:
    """A contract for another activity type, or one that ended, does not open the gate."""
    worker_id = save_worker(session=session, document_types=(DocumentType.QUALIFICATION,))
    other_type = build_authorisation(activity_types=('permanence',), worker_id=worker_id)
    ended = build_authorisation(
        activity_types=('courses',),
        end_date=TODAY - timedelta(days=1),
        worker_id=worker_id,
    )
    session.add_all([other_type, ended])
    session.flush()

    result = submit(session=session, worker_id=worker_id, form=build_form())

    assert result.outcome == 'no_contract'


def test_r12_10_contract_of_another_worker_type_does_not_open_the_gate(session: Session) -> None:
    """After a change of type the old contract no longer counts; one of the new type does."""
    worker_id = save_worker(session=session, worker_type=WorkerType.VRIJWILLIGER)
    worker = session.get(Worker, worker_id)
    worker.worker_type = WorkerType.ARTICLE_17
    session.flush()
    client = FakeDimonaClient(outcome='accept')

    refused = submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    assert refused.outcome == 'no_contract'
    assert 'aucun contrat Article 17 valide' in refused.message
    assert count_activities(session=session) == 0
    assert client.declarations == []

    new_contract = build_authorisation(
        activity_types=ACTIVITY_TYPE_CODES,
        start_date=START_DATE,
        worker_id=worker_id,
        worker_type=WorkerType.ARTICLE_17,
    )
    session.add(new_contract)
    session.flush()

    accepted = submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    assert accepted.outcome == 'accepted'


def test_r8_1_checks_run_in_order_and_stop_at_the_first_failure(session: Session) -> None:
    """Input before contract, contract before qualification."""
    worker_id = save_worker(session=session, document_types=())
    past_form = build_form(activity_date=TODAY - timedelta(days=1))

    past_result = submit(session=session, worker_id=worker_id, form=past_form)
    valid_result = submit(session=session, worker_id=worker_id, form=build_form())

    assert past_result.outcome == 'invalid_input'
    assert valid_result.outcome == 'no_contract'


def test_r8_3_hourly_compensation_is_stored_with_rate_and_model(session: Session) -> None:
    """Rate times hours, with copies of the rate, the model and the worker type (R17.3)."""
    worker_id = save_worker(session=session)
    form = build_form(activity_type='courses', duration_hours=Decimal('3'))

    result = submit(session=session, worker_id=worker_id, form=form)

    activity = session.get(Activity, result.activity_id)
    assert activity.compensation_model == CompensationModel.HOURLY
    assert activity.rate_applied == RATE
    assert activity.compensation_amount == Decimal('60.00')
    assert activity.duration_hours == Decimal('3')
    assert activity.worker_type == WorkerType.ARTICLE_17
    assert activity.activity_date == TODAY
    assert activity.is_cancelled is False


def test_r8_3_fixed_price_compensation_ignores_the_hours(session: Session) -> None:
    """A fixed-price activity is paid the rate once; the hours are still recorded (R7.5)."""
    worker_id = save_worker(session=session)
    form = build_form(activity_type='permanence', duration_hours=Decimal('4'))

    result = submit(session=session, worker_id=worker_id, form=form)

    activity = session.get(Activity, result.activity_id)
    assert activity.compensation_model == CompensationModel.FIXED
    assert activity.compensation_amount == RATE
    assert activity.duration_hours == Decimal('4')


def test_r8_3_rate_valid_on_the_activity_date_is_used(session: Session) -> None:
    """A newer rate version only applies from its own date on (R6.7)."""
    worker_id = save_worker(session=session)
    new_rate_date = TODAY + timedelta(days=10)
    new_rate = build_rate(valid_from=new_rate_date, amount=Decimal('25'), worker_id=worker_id)
    session.add(new_rate)
    session.flush()
    before_form = build_form(activity_date=TODAY, duration_hours=Decimal('1'))
    after_form = build_form(activity_date=new_rate_date, duration_hours=Decimal('1'))

    before_result = submit(session=session, worker_id=worker_id, form=before_form)
    after_result = submit(session=session, worker_id=worker_id, form=after_form)

    assert session.get(Activity, before_result.activity_id).rate_applied == Decimal('20')
    assert session.get(Activity, after_result.activity_id).rate_applied == Decimal('25')


@pytest.mark.parametrize('worker_type', [WorkerType.VRIJWILLIGER, WorkerType.FREELANCER])
def test_r8_4_activity_without_dimona_is_confirmed_at_once(
    session: Session,
    worker_type: WorkerType,
) -> None:
    """Volunteers and freelancers: status not applicable, no Dimona call, a confirmation."""
    worker_id = save_worker(session=session, worker_type=worker_type)
    client = FakeDimonaClient(outcome='reject')
    form = build_form(duration_hours=Decimal('2'))

    result = submit(session=session, worker_id=worker_id, form=form, dimona_client=client)

    activity = session.get(Activity, result.activity_id)
    assert result.outcome == 'confirmed'
    assert result.level == 'success'
    assert result.message == 'Activité confirmée. Rémunération : 40,00 €'
    assert activity.dimona_status == DimonaStatus.NOT_APPLICABLE
    assert activity.dimona_declaration_id is None
    assert client.declarations == []


@pytest.mark.parametrize('worker_type', [WorkerType.ARTICLE_17, WorkerType.FLEXI_JOB])
def test_r8_6_accepted_declaration_is_registered_ok_with_its_id(
    session: Session,
    worker_type: WorkerType,
) -> None:
    """Article 17 and flexi-job: declared, stored as ok with the returned ID, confirmed."""
    worker_id = save_worker(session=session, worker_type=worker_type)
    client = FakeDimonaClient(outcome='accept')

    result = submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    activity = session.get(Activity, result.activity_id)
    declaration = client.declarations[0]
    assert result.outcome == 'accepted'
    assert result.level == 'success'
    assert activity.dimona_status == DimonaStatus.OK
    assert activity.dimona_declaration_id.startswith('FAKE-')
    assert activity.dimona_declaration_id in result.message
    assert result.message.endswith('Rémunération : 60,00 €')
    assert len(client.declarations) == 1
    assert declaration.national_register_number == VALID_NATIONAL_REGISTER_NUMBER
    assert declaration.worker_type == worker_type
    assert declaration.activity_date == TODAY
    assert declaration.planned_hours == 3


def test_r7_15_flexi_job_start_time_is_stored_and_declared(session: Session) -> None:
    """The start time of a flexi-jobber is kept on the activity and sent with the declaration."""
    worker_id = save_worker(session=session, worker_type=WorkerType.FLEXI_JOB)
    client = FakeDimonaClient(outcome='accept')
    form = build_form(start_time=time(hour=17, minute=30))

    result = submit(session=session, worker_id=worker_id, form=form, dimona_client=client)

    activity = session.get(Activity, result.activity_id)
    assert activity.start_time == time(hour=17, minute=30)
    assert client.declarations[0].start_time == time(hour=17, minute=30)


def test_r7_15_start_time_is_not_kept_for_other_worker_types(session: Session) -> None:
    """Only a flexi-job has a start time: an article 17 activity stores and declares none."""
    worker_id = save_worker(session=session, worker_type=WorkerType.ARTICLE_17)
    client = FakeDimonaClient(outcome='accept')

    result = submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    activity = session.get(Activity, result.activity_id)
    assert activity.start_time is None
    assert client.declarations[0].start_time is None


@pytest.mark.parametrize('start_time', [None, time(hour=17, minute=15), time(hour=17, second=1)])
def test_r7_15_flexi_job_needs_a_start_time_on_the_half_hour(
    session: Session,
    start_time: Optional[time],
) -> None:
    """Without a start time, or off the half hour, nothing is registered or declared."""
    worker_id = save_worker(session=session, worker_type=WorkerType.FLEXI_JOB)
    client = FakeDimonaClient(outcome='accept')
    form = build_form(start_time=start_time)

    result = submit(session=session, worker_id=worker_id, form=form, dimona_client=client)

    assert result.outcome == 'invalid_input'
    assert result.message == (
        "Activité non enregistrée : indiquez l'heure de début, à l'heure pile ou à la demi-heure."
    )
    assert count_activities(session=session) == 0
    assert client.declarations == []


@pytest.mark.parametrize(
    ('today', 'latest_date'),
    [
        (date(2026, 10, 10), date(2026, 12, 31)),
        (date(2026, 11, 30), date(2026, 12, 31)),
        (date(2026, 12, 1), date(2027, 3, 1)),
        (date(2026, 12, 31), date(2027, 3, 31)),
        (date(2027, 1, 15), date(2027, 3, 31)),
        (date(2027, 3, 1), date(2027, 6, 1)),
    ],
)
def test_r7_16_flexi_job_calendar_follows_the_quarters(today: date, latest_date: date) -> None:
    """A quarter opens one month before it starts, and never further than 3 months ahead."""
    found = find_latest_date(today=today, worker_type=WorkerType.FLEXI_JOB)

    assert found == latest_date


def test_r7_16_other_worker_types_keep_the_three_months() -> None:
    """The quarter rule of the RSZ only concerns flexi-jobs."""
    found = find_latest_date(today=date(2026, 10, 10), worker_type=WorkerType.ARTICLE_17)

    assert found == date(2027, 1, 10)


def test_r7_16_flexi_job_in_a_quarter_that_is_not_open_is_refused(session: Session) -> None:
    """On 10 October a flexi-job in January is refused, with the latest date that works."""
    worker_id = save_worker(session=session, worker_type=WorkerType.FLEXI_JOB)
    client = FakeDimonaClient(outcome='accept')
    form = build_form(activity_date=date(2027, 1, 4))

    result = submit(session=session, worker_id=worker_id, form=form, dimona_client=client)

    assert result.outcome == 'invalid_input'
    assert result.message == (
        'Activité non enregistrée : une activité Flexijob se déclare au plus tôt un mois avant le '
        "début de son trimestre. Aujourd'hui, la date peut aller jusqu'au 31/12/2026."
    )
    assert count_activities(session=session) == 0
    assert client.declarations == []


def test_r7_16_flexi_job_in_the_next_quarter_is_accepted_from_one_month_before(
    session: Session,
) -> None:
    """From 1 December on, the same January activity is declared."""
    worker_id = save_worker(session=session, worker_type=WorkerType.FLEXI_JOB)
    form = build_form(activity_date=date(2027, 1, 4))

    result = submit(session=session, worker_id=worker_id, form=form, today=date(2026, 12, 1))

    assert result.outcome == 'accepted'


def test_r8_7_rejected_declaration_is_registered_rejected_with_the_reason(
    session: Session,
) -> None:
    """A rejection is stored with the reason of the service and shown as an error."""
    worker_id = save_worker(session=session)
    client = FakeDimonaClient(outcome='reject')

    result = submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    activity = session.get(Activity, result.activity_id)
    assert result.outcome == 'rejected'
    assert result.level == 'error'
    assert activity.dimona_message in result.message
    assert activity.dimona_status == DimonaStatus.REJECTED
    assert activity.dimona_declaration_id is None
    assert activity.dimona_message == 'déclaration refusée par le faux service Dimona'


def test_r8_8_declaration_without_answer_is_registered_pending(session: Session) -> None:
    """No answer within the time limit: stored as pending, shown as a warning."""
    worker_id = save_worker(session=session)
    client = FakeDimonaClient(outcome='timeout')

    result = submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    activity = session.get(Activity, result.activity_id)
    assert result.outcome == 'pending'
    assert result.level == 'warning'
    assert result.message.startswith('Activité enregistrée EN ATTENTE')
    assert activity.dimona_status == DimonaStatus.PENDING
    assert activity.dimona_declaration_id is None


def test_r16_3_gate_never_blocks_on_legal_limits(session: Session) -> None:
    """An activity far above a configured limit is still registered."""
    worker_id = save_worker(session=session)
    limit = build_limit(hours_limit=Decimal('1'), euro_limit=Decimal('1'))
    session.add(limit)
    session.flush()

    result = submit(session=session, worker_id=worker_id, form=build_form())

    assert result.outcome == 'accepted'


def test_r11_5_inactive_worker_cannot_declare(session: Session) -> None:
    """The gate itself refuses a deactivated worker, whatever the page does."""
    worker_id = save_worker(session=session, is_active=False)

    with pytest.raises(ValueError):
        submit(session=session, worker_id=worker_id, form=build_form())


def test_r8_3_missing_rate_is_a_data_error(session: Session) -> None:
    """A worker always has every rate; without one the gate stops instead of guessing."""
    worker = build_worker()
    session.add(worker)
    session.flush()
    for document_type in BOTH_DOCUMENTS:
        authorisation = build_authorisation(document_type=document_type, worker_id=worker.id)
        session.add(authorisation)
    session.flush()

    with pytest.raises(ValueError):
        submit(session=session, worker_id=worker.id, form=build_form())
    assert count_activities(session=session) == 0


def save_worker_with_supplement_rates(
    session: Session,
    worker_type: WorkerType = WorkerType.ARTICLE_17,
) -> int:
    """Store a ready worker whose two supplements pay 25 euro, apart from the other rates."""
    worker_id = save_worker(session=session, worker_type=worker_type)
    for supplement in SUPPLEMENT_CODES:
        rate = build_rate(
            valid_from=START_DATE + timedelta(days=1),
            amount=SUPPLEMENT_RATE,
            worker_id=worker_id,
            activity_type=supplement,
        )
        session.add(rate)
    session.flush()
    return worker_id


def test_r6_9_group_travel_is_added_to_a_group_course(session: Session) -> None:
    """Rate times hours plus the supplement; the supplement is stored apart (R8.3, R17.3)."""
    worker_id = save_worker_with_supplement_rates(session=session)
    form = build_form(activity_type='group_with_instructor', with_supplement=True)

    result = submit(session=session, worker_id=worker_id, form=form)

    activity = session.get(Activity, result.activity_id)
    assert result.outcome == 'accepted'
    assert activity.rate_applied == RATE
    assert activity.supplement_amount == SUPPLEMENT_RATE
    assert activity.compensation_amount == Decimal('85.00')


@pytest.mark.parametrize(
    'activity_type',
    ['route_setting_easy', 'route_setting_medium', 'route_setting_hard'],
)
def test_r6_9_rope_supplement_is_added_to_a_route_setting(
    session: Session,
    activity_type: str,
) -> None:
    """The fixed price of the route plus the supplement for ropes 9 to 14."""
    worker_id = save_worker_with_supplement_rates(session=session)
    form = build_form(activity_type=activity_type, description='Corde 11', with_supplement=True)

    result = submit(session=session, worker_id=worker_id, form=form)

    activity = session.get(Activity, result.activity_id)
    assert activity.supplement_amount == SUPPLEMENT_RATE
    assert activity.compensation_amount == Decimal('45.00')


def test_r6_9_without_the_tick_box_no_supplement_is_paid(session: Session) -> None:
    """A group course without travel is paid its hours only."""
    worker_id = save_worker_with_supplement_rates(session=session)
    form = build_form(activity_type='group_without_instructor')

    result = submit(session=session, worker_id=worker_id, form=form)

    activity = session.get(Activity, result.activity_id)
    assert activity.supplement_amount == Decimal('0')
    assert activity.compensation_amount == Decimal('60.00')


@pytest.mark.parametrize('activity_type', ['permanence', 'courses', 'route_cleaning_hard'])
def test_r6_9_activity_type_without_supplement_ignores_the_tick_box(
    session: Session,
    activity_type: str,
) -> None:
    """Only the group courses and the route settings offer a supplement."""
    worker_id = save_worker_with_supplement_rates(session=session)
    form = build_form(activity_type=activity_type, with_supplement=True)

    result = submit(session=session, worker_id=worker_id, form=form)

    activity = session.get(Activity, result.activity_id)
    assert result.outcome == 'accepted'
    assert activity.supplement_amount == Decimal('0')


@pytest.mark.parametrize('supplement', SUPPLEMENT_CODES)
def test_r6_9_supplement_cannot_be_declared_on_its_own(session: Session, supplement: str) -> None:
    """A supplement is not an activity type: nothing is registered or declared."""
    worker_id = save_worker_with_supplement_rates(session=session)
    client = FakeDimonaClient(outcome='accept')
    form = build_form(activity_type=supplement)

    with pytest.raises(ValueError):
        submit(session=session, worker_id=worker_id, form=form, dimona_client=client)
    assert count_activities(session=session) == 0
    assert client.declarations == []


def test_r6_10_supplement_adds_no_hours_and_no_declaration(session: Session) -> None:
    """One Dimona declaration, with the hours of the course itself."""
    worker_id = save_worker_with_supplement_rates(session=session)
    client = FakeDimonaClient(outcome='accept')
    form = build_form(
        activity_type='group_with_instructor',
        duration_hours=Decimal('3'),
        with_supplement=True,
    )

    result = submit(session=session, worker_id=worker_id, form=form, dimona_client=client)

    activity = session.get(Activity, result.activity_id)
    assert count_activities(session=session) == 1
    assert activity.duration_hours == Decimal('3')
    assert [declaration.planned_hours for declaration in client.declarations] == [3]


def test_r6_10_supplement_counts_in_the_confirmed_amount(session: Session) -> None:
    """The message of a volunteer names the compensation with the supplement."""
    worker_id = save_worker_with_supplement_rates(
        session=session,
        worker_type=WorkerType.VRIJWILLIGER,
    )
    form = build_form(activity_type='group_with_instructor', with_supplement=True)

    result = submit(session=session, worker_id=worker_id, form=form)

    assert result.outcome == 'confirmed'
    assert result.message == f'Activité confirmée. Rémunération : 85,00{NO_BREAK_SPACE}€'


def test_r6_11_second_group_travel_on_the_same_day_is_refused(session: Session) -> None:
    """Group travel is paid once per day, whichever group course carries it."""
    worker_id = save_worker_with_supplement_rates(session=session)
    client = FakeDimonaClient(outcome='accept')
    first_form = build_form(activity_type='group_with_instructor', with_supplement=True)
    second_form = build_form(activity_type='group_without_instructor', with_supplement=True)
    submit(session=session, worker_id=worker_id, form=first_form, dimona_client=client)

    result = submit(session=session, worker_id=worker_id, form=second_form, dimona_client=client)

    assert result.outcome == 'invalid_input'
    assert result.level == 'error'
    assert result.message == (
        'Activité non enregistrée : le déplacement groupe est déjà déclaré pour ce jour. '
        'Il est payé au maximum une fois par jour.'
    )
    assert count_activities(session=session) == 1
    assert len(client.declarations) == 1


def test_r6_11_second_group_course_without_travel_is_accepted(session: Session) -> None:
    """Only the supplement is limited: a second course on the day is registered without it."""
    worker_id = save_worker_with_supplement_rates(session=session)
    first_form = build_form(activity_type='group_with_instructor', with_supplement=True)
    second_form = build_form(activity_type='group_with_instructor')
    submit(session=session, worker_id=worker_id, form=first_form)

    result = submit(session=session, worker_id=worker_id, form=second_form)

    assert result.outcome == 'accepted'
    assert count_activities(session=session) == 2


def test_r6_11_group_travel_on_another_day_is_accepted(session: Session) -> None:
    """The limit is per day."""
    worker_id = save_worker_with_supplement_rates(session=session)
    first_form = build_form(activity_type='group_with_instructor', with_supplement=True)
    next_day_form = build_form(
        activity_date=TODAY + timedelta(days=1),
        activity_type='group_with_instructor',
        with_supplement=True,
    )
    submit(session=session, worker_id=worker_id, form=first_form)

    result = submit(session=session, worker_id=worker_id, form=next_day_form)

    activity = session.get(Activity, result.activity_id)
    assert result.outcome == 'accepted'
    assert activity.supplement_amount == SUPPLEMENT_RATE


def test_r6_11_group_travel_of_another_worker_does_not_count(session: Session) -> None:
    """The limit is per worker."""
    worker_id = save_worker_with_supplement_rates(session=session)
    other_worker = build_worker(
        username='other',
        national_register_number=OTHER_NATIONAL_REGISTER_NUMBER,
    )
    session.add(other_worker)
    session.flush()
    other_activity = build_activity(
        worker_id=other_worker.id,
        activity_date=TODAY,
        activity_type='group_with_instructor',
        supplement_amount=SUPPLEMENT_RATE,
    )
    session.add(other_activity)
    session.flush()
    form = build_form(activity_type='group_with_instructor', with_supplement=True)

    result = submit(session=session, worker_id=worker_id, form=form)

    assert result.outcome == 'accepted'


def test_r6_11_cancelled_group_travel_does_not_count(session: Session) -> None:
    """Only counted activities use up the group travel of the day (R17.2)."""
    worker_id = save_worker_with_supplement_rates(session=session)
    form = build_form(activity_type='group_with_instructor', with_supplement=True)
    first_result = submit(session=session, worker_id=worker_id, form=form)
    session.get(Activity, first_result.activity_id).is_cancelled = True
    session.flush()

    result = submit(session=session, worker_id=worker_id, form=form)

    assert result.outcome == 'accepted'


def test_r6_11_rejected_group_travel_does_not_count(session: Session) -> None:
    """A Dimona-rejected activity is not counted, so the travel can be declared again."""
    worker_id = save_worker_with_supplement_rates(session=session)
    form = build_form(activity_type='group_with_instructor', with_supplement=True)
    rejecting_client = FakeDimonaClient(outcome='reject')
    submit(session=session, worker_id=worker_id, form=form, dimona_client=rejecting_client)

    result = submit(session=session, worker_id=worker_id, form=form)

    assert result.outcome == 'accepted'


def test_r6_11_rope_supplement_is_paid_for_every_route_of_the_day(session: Session) -> None:
    """One route is one activity: two routes on ropes 9 to 14 are two supplements (R6.5)."""
    worker_id = save_worker_with_supplement_rates(session=session)
    form = build_form(
        activity_type='route_setting_medium',
        description='Corde 12',
        with_supplement=True,
    )
    submit(session=session, worker_id=worker_id, form=form)

    result = submit(session=session, worker_id=worker_id, form=form)

    activity = session.get(Activity, result.activity_id)
    assert result.outcome == 'accepted'
    assert activity.supplement_amount == SUPPLEMENT_RATE
    assert count_activities(session=session) == 2


def test_r8_3_missing_supplement_rate_is_a_data_error(session: Session) -> None:
    """Without the rate of the supplement the gate stops instead of paying nothing."""
    worker = build_worker()
    session.add(worker)
    session.flush()
    session.add(build_rate(valid_from=START_DATE, worker_id=worker.id, activity_type='courses'))
    group_rate = build_rate(
        valid_from=START_DATE,
        worker_id=worker.id,
        activity_type='group_with_instructor',
    )
    session.add(group_rate)
    for document_type in BOTH_DOCUMENTS:
        authorisation = build_authorisation(
            document_type=document_type,
            activity_types=('group_with_instructor',),
            worker_id=worker.id,
        )
        session.add(authorisation)
    session.flush()
    form = build_form(activity_type='group_with_instructor', with_supplement=True)

    with pytest.raises(ValueError):
        submit(session=session, worker_id=worker.id, form=form)
    assert count_activities(session=session) == 0


def save_day_activity(
    session: Session,
    worker_id: int,
    dimona_status: DimonaStatus = DimonaStatus.OK,
    dimona_declaration_id: Optional[str] = '111',
    is_cancelled: bool = False,
    activity_date: date = TODAY,
) -> Activity:
    """Store an article 17 activity of 2 hours the worker already declared."""
    activity = build_activity(
        worker_id=worker_id,
        activity_date=activity_date,
        dimona_status=dimona_status,
        dimona_declaration_id=dimona_declaration_id,
        is_cancelled=is_cancelled,
    )
    session.add(activity)
    session.flush()
    return activity


def test_r8_9_second_article_17_activity_of_the_day_updates_the_period(session: Session) -> None:
    """The first activity opens the period, the second raises its hours; no second Dimona IN."""
    worker_id = save_worker(session=session)
    client = FakeDimonaClient(outcome='accept')
    first = submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)
    first_activity = session.get(Activity, first.activity_id)
    form = build_form(activity_type='route_setting_easy', description='Mur nord')

    result = submit(session=session, worker_id=worker_id, form=form, dimona_client=client)

    activity = session.get(Activity, result.activity_id)
    assert len(client.declarations) == 1
    assert client.hour_updates == [(first_activity.dimona_declaration_id, 6)]
    assert result.outcome == 'accepted'
    assert activity.dimona_status == DimonaStatus.OK
    assert activity.dimona_declaration_id.startswith('FAKE-')
    assert activity.dimona_declaration_id != first_activity.dimona_declaration_id


def test_r8_9_period_hours_are_those_of_all_accepted_activities_of_the_day(
    session: Session,
) -> None:
    """Accepted activities count; cancelled and rejected ones do not; the latest leads on."""
    worker_id = save_worker(session=session)
    save_day_activity(session=session, worker_id=worker_id, dimona_declaration_id='111')
    save_day_activity(session=session, worker_id=worker_id, dimona_declaration_id='222')
    save_day_activity(
        session=session,
        worker_id=worker_id,
        dimona_declaration_id='333',
        is_cancelled=True,
    )
    save_day_activity(
        session=session,
        worker_id=worker_id,
        dimona_status=DimonaStatus.REJECTED,
        dimona_declaration_id=None,
    )
    client = FakeDimonaClient(outcome='accept')

    submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    assert client.declarations == []
    assert client.hour_updates == [('222', 7)]


@pytest.mark.parametrize(
    ('dimona_status', 'is_cancelled', 'activity_date'),
    [
        (DimonaStatus.REJECTED, False, TODAY),
        (DimonaStatus.OK, True, TODAY),
        (DimonaStatus.OK, False, TODAY + timedelta(days=1)),
    ],
)
def test_r8_9_without_an_accepted_activity_that_day_a_period_is_opened(
    session: Session,
    dimona_status: DimonaStatus,
    is_cancelled: bool,
    activity_date: date,
) -> None:
    """A rejected or cancelled activity, or one on another day, leaves no period to update."""
    worker_id = save_worker(session=session)
    declaration_id = '111' if dimona_status == DimonaStatus.OK else None
    save_day_activity(
        session=session,
        worker_id=worker_id,
        dimona_status=dimona_status,
        dimona_declaration_id=declaration_id,
        is_cancelled=is_cancelled,
        activity_date=activity_date,
    )
    client = FakeDimonaClient(outcome='accept')

    submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    assert len(client.declarations) == 1
    assert client.hour_updates == []


def test_r8_9_activity_of_another_worker_does_not_count(session: Session) -> None:
    """The period of the day belongs to one worker."""
    worker_id = save_worker(session=session)
    other_worker = build_worker(
        username='other',
        national_register_number=OTHER_NATIONAL_REGISTER_NUMBER,
    )
    session.add(other_worker)
    session.flush()
    save_day_activity(session=session, worker_id=other_worker.id)
    client = FakeDimonaClient(outcome='accept')

    submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    assert len(client.declarations) == 1
    assert client.hour_updates == []


def test_r8_9_flexi_job_keeps_one_declaration_per_activity(session: Session) -> None:
    """Only article 17 shares one period per day; a flexi-job declares each activity."""
    worker_id = save_worker(session=session, worker_type=WorkerType.FLEXI_JOB)
    client = FakeDimonaClient(outcome='accept')
    later_form = build_form(start_time=time(hour=20))

    submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)
    submit(session=session, worker_id=worker_id, form=later_form, dimona_client=client)

    assert len(client.declarations) == 2
    assert client.hour_updates == []


@pytest.mark.parametrize(
    ('fake_outcome', 'dimona_status'),
    [('reject', DimonaStatus.REJECTED), ('timeout', DimonaStatus.PENDING)],
)
def test_r8_9_update_answer_is_stored_on_the_new_activity(
    session: Session,
    fake_outcome: str,
    dimona_status: DimonaStatus,
) -> None:
    """A refused or unanswered update is stored like any declaration (R8.7, R8.8)."""
    worker_id = save_worker(session=session)
    first_activity = save_day_activity(session=session, worker_id=worker_id)
    client = FakeDimonaClient(outcome=fake_outcome)

    result = submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    activity = session.get(Activity, result.activity_id)
    assert client.hour_updates == [('111', 5)]
    assert activity.dimona_status == dimona_status
    assert activity.dimona_declaration_id is None
    assert first_activity.dimona_status == DimonaStatus.OK


def test_r8_10_pending_declaration_that_day_refuses_a_new_activity(session: Session) -> None:
    """While the hours at the RSZ are unknown, nothing is sent and nothing is registered."""
    worker_id = save_worker(session=session)
    save_day_activity(session=session, worker_id=worker_id)
    save_day_activity(
        session=session,
        worker_id=worker_id,
        dimona_status=DimonaStatus.PENDING,
        dimona_declaration_id=None,
    )
    client = FakeDimonaClient(outcome='accept')

    result = submit(session=session, worker_id=worker_id, form=build_form(), dimona_client=client)

    assert result.outcome == 'pending_day'
    assert result.level == 'error'
    assert result.message == (
        'Activité non enregistrée : une déclaration Dimona de ce jour est encore en attente. '
        "Réessayez quand un administrateur l'aura résolue."
    )
    assert result.activity_id is None
    assert count_activities(session=session) == 2
    assert client.declarations == []
    assert client.hour_updates == []


def test_r8_10_pending_declaration_on_another_day_does_not_refuse(session: Session) -> None:
    """Only a pending declaration of the same day stops the gate."""
    worker_id = save_worker(session=session)
    save_day_activity(
        session=session,
        worker_id=worker_id,
        dimona_status=DimonaStatus.PENDING,
        dimona_declaration_id=None,
        activity_date=TODAY + timedelta(days=1),
    )

    result = submit(session=session, worker_id=worker_id, form=build_form())

    assert result.outcome == 'accepted'
