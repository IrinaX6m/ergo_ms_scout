"""Календарь ежедневного расписания с явной обработкой перевода часов."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

START_WINDOW_SECONDS = 900


def scheduled_time(day, local_time, zone):
    wall = datetime.combine(day, local_time)
    candidates = []
    projections = []
    for fold in (0, 1):
        utc = wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        projections.append(utc)
        if utc.astimezone(zone).replace(tzinfo=None) == wall:
            candidates.append(utc)
    if candidates:
        return min(candidates), min(candidates)
    return None, max(projections)


def first_future_date(now, local_time, timezone_name):
    zone = ZoneInfo(timezone_name)
    day = now.astimezone(zone).date()
    _scheduled, process_at = scheduled_time(day, local_time, zone)
    return day if process_at > now else day + timedelta(days=1)


def next_scheduled_at(revision, now):
    if not revision.enabled:
        return None
    zone = ZoneInfo(revision.timezone)
    day = max(revision.first_local_date, now.astimezone(zone).date())
    while True:
        scheduled, _process_at = scheduled_time(day, revision.local_time, zone)
        if scheduled is not None and scheduled > now:
            if not revision.schedule.occurrences.filter(local_date=day).exists():
                return scheduled
        day += timedelta(days=1)
