"""Den AMP-Zeitplan einer Instanz lesen: welche Zeit-Trigger starten neu, stoppen oder
aktualisieren den Server, und wann laufen sie das naechste Mal?

AMP liefert ueber Core/GetScheduleData die Trigger samt Aufgaben; die genauen Zeiten
eines Zeit-Triggers ueber Core/GetTimeIntervalTrigger (MatchMinutes/-Hours/-Days/
-DaysOfMonth/-Months). Leere Liste = jeder Wert. Wochentage wie in .NET (0 = Sonntag).
Ausgewertet in der Zeitzone der Community (TIMEZONE) - ob das zur AMP-Uhr passt, zeigt
die Vorschau im Tab "Server-News", bevor angekuendigt wird.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

# Aufgaben, die den Server unterbrechen -> (Art, Text)
TASK_KINDS = (
    ("restart", "Neustart"),
    ("update", "Update"),
    ("stop", "Stopp"),
)
LOOKAHEAD_DAYS = 8


@dataclass
class PlannedRun:
    trigger_id: str
    kind: str  # restart | update | stop
    label: str  # Beschreibung des Triggers in AMP
    at: datetime  # naechster Lauf, lokale Zeit ohne Zeitzone


def task_kind(method_name: str) -> str | None:
    """Art einer Aufgabe nach ihrem Methodennamen (z.B. "Core.RestartApplication")."""
    name = (method_name or "").lower()
    if "restart" in name:
        return "restart"
    if "update" in name and "application" in name:
        return "update"
    if "stop" in name and ("application" in name or "instance" in name):
        return "stop"
    return None


def _enabled(item: dict) -> bool:
    state = item.get("EnabledState", 1)
    if isinstance(state, str):
        return state.lower() != "disabled"
    return int(state or 0) != 0


def interrupting_triggers(schedule: dict) -> list[tuple[str, str, str]]:
    """(Trigger-ID, Art, Beschreibung) aller aktiven Trigger mit Neustart/Update/Stopp - ob es ein
    Zeit-Trigger ist, zeigt erst GetTimeIntervalTrigger (Ereignis-Trigger haben keine Zeiten)."""
    found = []
    for trigger in schedule.get("PopulatedTriggers") or []:
        if not isinstance(trigger, dict) or not _enabled(trigger):
            continue
        kinds = [task_kind(t.get("TaskMethodName", "")) for t in trigger.get("Tasks") or [] if isinstance(t, dict) and _enabled(t)]
        kinds = [k for k in kinds if k]
        if not kinds:
            continue
        # wichtigste Art zuerst: Update > Neustart > Stopp
        kind = next(k for k, _ in (("update", 0), ("restart", 0), ("stop", 0)) if k in kinds)
        found.append((str(trigger.get("Id")), kind, str(trigger.get("Description") or "")))
    return found


def next_run(interval: dict, after: datetime) -> datetime | None:
    """Naechster passende Minute nach `after` (lokale Zeit), hoechstens LOOKAHEAD_DAYS voraus."""
    minutes = set(interval.get("MatchMinutes") or [])
    hours = set(interval.get("MatchHours") or [])
    weekdays = set(interval.get("MatchDays") or [])  # 0 = Sonntag (.NET)
    days = set(interval.get("MatchDaysOfMonth") or [])
    months = set(interval.get("MatchMonths") or [])
    current = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = after + timedelta(days=LOOKAHEAD_DAYS)
    while current <= end:
        if months and current.month not in months:
            current = (current.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            continue
        dotnet_weekday = (current.weekday() + 1) % 7  # Python: 0 = Montag
        if (days and current.day not in days) or (weekdays and dotnet_weekday not in weekdays):
            current = current.replace(hour=0, minute=0) + timedelta(days=1)
            continue
        if hours and current.hour not in hours:
            current = current.replace(minute=0) + timedelta(hours=1)
            continue
        if minutes and current.minute not in minutes:
            current += timedelta(minutes=1)
            continue
        return current
    return None


async def planned_runs(instance_call, instance_id: str, now_local: datetime) -> list[PlannedRun]:
    """Naechste Laeufe aller unterbrechenden Zeit-Trigger einer Instanz.
    instance_call(instance_id, endpoint, args) - z.B. amp_client.instance_core_call."""
    schedule = await instance_call(instance_id, "GetScheduleData", {})
    runs = []
    for trigger_id, kind, label in interrupting_triggers(schedule if isinstance(schedule, dict) else {}):
        try:
            interval = await instance_call(instance_id, "GetTimeIntervalTrigger", {"Id": trigger_id})
        except Exception:  # kein Zeit-Trigger (z.B. "Update verfuegbar") - nicht vorhersagbar
            continue
        if not isinstance(interval, dict) or not any(k.startswith("Match") for k in interval):
            continue
        when = next_run(interval, now_local)
        if when is not None:
            runs.append(PlannedRun(trigger_id, kind, label, when))
    return sorted(runs, key=lambda r: r.at)
