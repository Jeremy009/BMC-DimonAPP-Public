"""The calendar of the accepted activities of the month on the dashboard (R10.8)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from dimonapp.french import NO_BREAK_SPACE
from dimonapp.models import DimonaStatus
from dimonapp.month_calendar import (
    CalendarEntry,
    build_calendar_html,
    build_event_html,
    build_legend_html,
    find_calendar_entries,
)
from factories import build_activity, build_worker

OCTOBER = date(2026, 10, 1)
ACTIVITY_LABELS = {
    'permanence': 'Permanence',
    'courses': 'Cours BMC',
    'group_without_instructor': 'Cours groupe sans mono',
    'route_setting_easy': 'Ouverture 4A - 5C',
}


def build_entry(
    activity_date: date = date(2026, 10, 7),
    worker_name: str = 'Noor Exemple',
    activity_type: str = 'courses',
) -> CalendarEntry:
    """Build a calendar entry of two and a half hours."""
    return CalendarEntry(
        activity_date=activity_date,
        worker_name=worker_name,
        activity_type=activity_type,
        hours=Decimal('2.5'),
    )


def save_worker(session: Session, username: str, first_name: str, number: str) -> int:
    """Store a worker and give the id."""
    worker = build_worker(
        national_register_number=number,
        username=username,
        first_name=first_name,
        last_name='Exemple',
    )
    session.add(worker)
    session.flush()
    return worker.id


def test_r10_8_entries_hold_the_accepted_activities_of_the_month_by_day_then_name(
    session: Session,
) -> None:
    """Dimona "ok" and no Dimona stay; pending, rejected, cancelled and other months do not."""
    zoe_id = save_worker(session=session, username='z', first_name='Zoé', number='1')
    alex_id = save_worker(session=session, username='a', first_name='Alex', number='2')
    activities = [
        build_activity(worker_id=zoe_id, activity_date=date(2026, 10, 7)),
        build_activity(
            worker_id=alex_id,
            activity_date=date(2026, 10, 7),
            dimona_status=DimonaStatus.NOT_APPLICABLE,
        ),
        build_activity(
            worker_id=zoe_id,
            activity_date=date(2026, 10, 2),
            dimona_status=DimonaStatus.PENDING,
        ),
        build_activity(
            worker_id=zoe_id,
            activity_date=date(2026, 10, 3),
            dimona_status=DimonaStatus.REJECTED,
        ),
        build_activity(worker_id=alex_id, activity_date=date(2026, 10, 4), is_cancelled=True),
        build_activity(worker_id=zoe_id, activity_date=date(2026, 9, 30)),
        build_activity(worker_id=zoe_id, activity_date=date(2026, 11, 1)),
    ]
    session.add_all(activities)
    session.flush()

    entries = find_calendar_entries(session=session, month_start=OCTOBER)

    summary = [(entry.activity_date.day, entry.worker_name) for entry in entries]
    assert summary == [(7, 'Alex Exemple'), (7, 'Zoé Exemple')]


def test_r10_8_calendar_runs_monday_to_sunday_over_every_day_of_the_month() -> None:
    """October 2026 starts on a Thursday and ends on a Saturday: four days of other months."""
    calendar_html = build_calendar_html(
        month_start=OCTOBER,
        entries=[build_entry()],
        activity_labels=ACTIVITY_LABELS,
    )

    heads = [f'<div class="bmc-cal-head">{name}</div>' for name in ('Lun', 'Mar', 'Dim')]
    positions = [calendar_html.index(head) for head in heads]
    assert positions == sorted(positions)
    assert calendar_html.count('class="bmc-cal-date"') == 31
    assert calendar_html.count('class="bmc-cal-day bmc-cal-outside"') == 4
    assert '<span class="bmc-cal-weekday">Mercredi </span>7</div>' in calendar_html
    assert calendar_html.count('class="bmc-cal-event"') == 1


def test_r10_8_block_shows_the_name_and_the_hours_in_bold_in_the_type_colour() -> None:
    """No amount and no activity type in the block: the colour tells the type."""
    event_html = build_event_html(entry=build_entry(), activity_labels=ACTIVITY_LABELS)

    name_html = '<span class="bmc-cal-name">Noor Exemple</span>'
    hours_html = f'<strong class="bmc-cal-hours">2,5{NO_BREAK_SPACE}h</strong>'
    assert f'{name_html}{hours_html}' in event_html
    assert '€' not in event_html
    assert '>Cours BMC<' not in event_html
    assert 'title="Cours BMC"' in event_html


def test_r10_8_each_family_of_activity_types_has_its_own_hue() -> None:
    """Permanence green, courses in blues, route setting yellow."""
    accents = {}
    for activity_type in ACTIVITY_LABELS:
        entry = build_entry(activity_type=activity_type)
        event_html = build_event_html(entry=entry, activity_labels=ACTIVITY_LABELS)
        accents[activity_type] = event_html.split('--accent: ')[1].split(';')[0]

    assert accents == {
        'permanence': '#16a34a',
        'courses': '#0ea5e9',
        'group_without_instructor': '#3b82f6',
        'route_setting_easy': '#eab308',
    }


def test_r10_8_worker_name_is_escaped() -> None:
    """A name from the database cannot inject HTML into the page."""
    entry = build_entry(worker_name='<b>Noor</b> & Co')

    event_html = build_event_html(entry=entry, activity_labels=ACTIVITY_LABELS)

    assert '&lt;b&gt;Noor&lt;/b&gt; &amp; Co' in event_html
    assert '<b>Noor</b>' not in event_html


def test_r10_8_legend_lists_only_the_activity_types_of_the_month() -> None:
    """Types without an activity in the month stay out of the legend, in the sheet order."""
    entries = [
        build_entry(activity_type='route_setting_easy'),
        build_entry(activity_type='permanence'),
    ]

    legend_html = build_legend_html(entries=entries, activity_labels=ACTIVITY_LABELS)

    assert legend_html.index('Permanence') < legend_html.index('Ouverture 4A - 5C')
    assert 'Cours BMC' not in legend_html
