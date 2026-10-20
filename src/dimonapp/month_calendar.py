"""The calendar of the dashboard: the accepted activities of the month on their day (R10.8).

Plain functions that build HTML; the dashboard draws it with st.html. A block holds the
worker's name and the hours; the colour tells the activity type. Names and labels come from
the database, so they are escaped.
"""

import calendar
import html
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import Session

from dimonapp.french import WEEKDAY_NAMES, format_hours
from dimonapp.models import Activity, DimonaStatus, Worker
from dimonapp.months import shift_month
from dimonapp.worker_types import build_worker_name

# Background and border of a block per activity type: permanence green, courses in blues,
# route setting from yellow to red by grade and route cleaning in amber and dark red.
ACTIVITY_COLOURS = {
    'permanence': ('#dcfce7', '#16a34a'),
    'courses': ('#e0f2fe', '#0ea5e9'),
    'group_without_instructor': ('#dbeafe', '#3b82f6'),
    'group_with_instructor': ('#c7d7fe', '#1e3a8a'),
    'route_setting_easy': ('#fef9c3', '#eab308'),
    'route_setting_medium': ('#ffedd5', '#f97316'),
    'route_setting_hard': ('#fee2e2', '#dc2626'),
    'route_cleaning_easy': ('#fef3c7', '#b45309'),
    'route_cleaning_hard': ('#fecaca', '#7f1d1d'),
}
OTHER_COLOURS = ('#f1f5f9', '#64748b')
# Accepted: Dimona "ok", or no Dimona at all; a pending declaration is not accepted yet.
ACCEPTED_STATUSES = (DimonaStatus.OK, DimonaStatus.NOT_APPLICABLE)

# The grid shows seven columns; on a phone it becomes a list of the days with activities.
CALENDAR_STYLE = """
<style>
.bmc-cal-legend {display: flex; flex-wrap: wrap; gap: 0.3rem 1rem; margin-bottom: 0.6rem;}
.bmc-cal-key {display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.85rem;}
.bmc-cal-swatch {
    display: inline-block;
    width: 0.9rem;
    height: 0.9rem;
    border-radius: 3px;
    background: var(--bg);
    border: 2px solid var(--accent);
}
.bmc-cal-grid {display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px;}
.bmc-cal-head {font-size: 0.85rem; font-weight: 600; color: #6b7280; padding: 0 4px;}
.bmc-cal-day {
    min-width: 0;
    min-height: 4.5rem;
    padding: 4px;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    background: #ffffff;
}
.bmc-cal-outside {background: #f9fafb; border-color: #f3f4f6;}
.bmc-cal-date {font-size: 0.8rem; color: #6b7280; margin-bottom: 2px;}
.bmc-cal-weekday {display: none;}
.bmc-cal-event {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 4px;
    margin-bottom: 3px;
    padding: 2px 4px;
    border-radius: 4px;
    font-size: 0.75rem;
    line-height: 1.3;
    color: #1f2937;
    background: var(--bg);
    border: 1px solid var(--accent);
    border-left-width: 4px;
}
.bmc-cal-name {min-width: 0; overflow-wrap: anywhere;}
.bmc-cal-hours {white-space: nowrap;}
@media (max-width: 640px) {
    .bmc-cal-grid {grid-template-columns: minmax(0, 1fr);}
    .bmc-cal-head, .bmc-cal-outside, .bmc-cal-empty {display: none;}
    .bmc-cal-day {min-height: 0;}
    .bmc-cal-weekday {display: inline;}
    .bmc-cal-event {font-size: 0.85rem;}
}
</style>
"""


class CalendarEntry(BaseModel):
    """One activity as the calendar shows it."""

    activity_date: date
    worker_name: str
    activity_type: str
    hours: Decimal


def find_calendar_entries(session: Session, month_start: date) -> list[CalendarEntry]:
    """Give the accepted activities of one month: not cancelled, Dimona "ok" or none (R10.8).

    Sorted by day, then by worker name, so a day lists its workers alphabetically.
    """
    next_month_start = shift_month(month_start=month_start, n_months=1)
    query = (
        sa.select(Activity, Worker)
        .join(Worker, Worker.id == Activity.worker_id)
        .where(
            Activity.activity_date >= month_start,
            Activity.activity_date < next_month_start,
            Activity.is_cancelled.is_(False),
            Activity.dimona_status.in_(ACCEPTED_STATUSES),
        )
        .order_by(Activity.activity_date, Worker.last_name, Worker.first_name, Activity.id)
    )
    entries = []
    for activity, worker in session.execute(query):
        entry = CalendarEntry(
            activity_date=activity.activity_date,
            worker_name=build_worker_name(worker=worker),
            activity_type=activity.activity_type,
            hours=activity.duration_hours,
        )
        entries.append(entry)
    return entries


def build_colour_style(activity_type: str) -> str:
    """Give the inline style that colours a block or a legend swatch by activity type."""
    background, accent = ACTIVITY_COLOURS.get(activity_type, OTHER_COLOURS)
    return f'--bg: {background}; --accent: {accent};'


def build_event_html(entry: CalendarEntry, activity_labels: dict[str, str]) -> str:
    """Build the block of one activity: the worker's name, then the hours in bold on the right.

    The activity type is not written: the colour tells it, and the label shows on hover.
    """
    name = html.escape(entry.worker_name)
    label = html.escape(activity_labels[entry.activity_type])
    hours = format_hours(hours=entry.hours)
    style = build_colour_style(activity_type=entry.activity_type)
    name_html = f'<span class="bmc-cal-name">{name}</span>'
    hours_html = f'<strong class="bmc-cal-hours">{hours}</strong>'
    return (
        f'<div class="bmc-cal-event" style="{style}" title="{label}">{name_html}{hours_html}</div>'
    )


def build_day_html(
    day: date,
    month_start: date,
    entries: list[CalendarEntry],
    activity_labels: dict[str, str],
) -> str:
    """Build the cell of one day; a day of the previous or next month stays empty."""
    if day.month != month_start.month:
        return '<div class="bmc-cal-day bmc-cal-outside"></div>'
    day_entries = [entry for entry in entries if entry.activity_date == day]
    events = [
        build_event_html(entry=entry, activity_labels=activity_labels) for entry in day_entries
    ]
    class_names = 'bmc-cal-day' if events else 'bmc-cal-day bmc-cal-empty'
    # The weekday name only shows on a phone, where the column headers are hidden
    weekday = WEEKDAY_NAMES[day.weekday()].capitalize()
    weekday_html = f'<span class="bmc-cal-weekday">{weekday} </span>'
    date_html = f'<div class="bmc-cal-date">{weekday_html}{day.day}</div>'
    events_html = ''.join(events)
    return f'<div class="{class_names}">{date_html}{events_html}</div>'


def build_legend_html(entries: list[CalendarEntry], activity_labels: dict[str, str]) -> str:
    """Build the legend: the colours of the activity types of the month."""
    month_types = {entry.activity_type for entry in entries}
    keys = []
    for activity_type in activity_labels:
        if activity_type not in month_types:
            continue
        style = build_colour_style(activity_type=activity_type)
        label = html.escape(activity_labels[activity_type])
        swatch = f'<span class="bmc-cal-swatch" style="{style}"></span>'
        keys.append(f'<span class="bmc-cal-key">{swatch}{label}</span>')
    keys_html = ''.join(keys)
    return f'<div class="bmc-cal-legend">{keys_html}</div>'


def build_calendar_html(
    month_start: date,
    entries: list[CalendarEntry],
    activity_labels: dict[str, str],
) -> str:
    """Build the calendar of one month, Monday to Sunday, with its legend."""
    heads = [f'<div class="bmc-cal-head">{name[:3].capitalize()}</div>' for name in WEEKDAY_NAMES]
    month_calendar = calendar.Calendar(firstweekday=calendar.MONDAY)
    days = month_calendar.itermonthdates(year=month_start.year, month=month_start.month)
    cells = [
        build_day_html(
            day=day,
            month_start=month_start,
            entries=entries,
            activity_labels=activity_labels,
        )
        for day in days
    ]
    legend_html = build_legend_html(entries=entries, activity_labels=activity_labels)
    grid_html = ''.join([*heads, *cells])
    return (
        f'{CALENDAR_STYLE}<div class="bmc-cal">{legend_html}'
        f'<div class="bmc-cal-grid">{grid_html}</div></div>'
    )
