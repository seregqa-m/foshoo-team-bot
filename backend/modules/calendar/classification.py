"""Event type tags and show names are independent parts of a calendar title."""
import re


EVENT_TYPES = {
    "спект": "performance",
    "спектакль": "performance",
    "реп": "rehearsal",
    "репетиция": "rehearsal",
}
SHOW_ALIASES = {"лг": "Любовь Громова"}
BRACKETS = re.compile(r"\[([^\[\]]*)\]|\(([^()]*)\)")
TYPE_WORD = re.compile(r"(?<!\w)(спектакль|спект|репетиция|реп)(?!\w)", re.IGNORECASE)


def _normalize(value):
    return " ".join((value or "").split()).casefold()


def event_name_text(title):
    """Keep bracketed show names; omit only brackets containing a type tag."""
    def replace(match):
        value = next(group for group in match.groups() if group is not None)
        return " " if _normalize(value).rstrip(".") in EVENT_TYPES else f" {value} "
    return _normalize(BRACKETS.sub(replace, title or ""))


def classify_event(title, show_names=()):
    """Explicit recognized tags override the legacy inference from a show name.

    No I/O: callers can supply the current show catalog when it is available.
    Aliases match whole words, so ЛГ never matches inside another word.
    """
    title = title or ""
    bracket_values = [next(group for group in match.groups() if group is not None)
                      for match in BRACKETS.finditer(title)]
    event_type = next((EVENT_TYPES[tag] for raw in bracket_values
                       if (tag := _normalize(raw).rstrip(".")) in EVENT_TYPES), None)
    # A type word outside brackets also supports "Репетиция [Название]".
    # Do not interpret words within a bracketed show name as its event type.
    if event_type is None:
        type_word = TYPE_WORD.search(BRACKETS.sub(" ", title))
        if type_word:
            event_type = EVENT_TYPES[_normalize(type_word.group())]
    name_part = event_name_text(title)
    names = {_normalize(name): name.strip() for name in show_names if _normalize(name)}
    for name in SHOW_ALIASES.values():
        names.setdefault(_normalize(name), name)
    show_name = next((names[name] for name in sorted(names, key=len, reverse=True)
                      if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", name_part)), None)
    if show_name is None:
        show_name = next((names[_normalize(name)] for alias, name in SHOW_ALIASES.items()
                          if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", name_part)), None)
    return {"event_type": event_type or ("performance" if show_name else None),
            "show_name": show_name}


def is_performance(title, show_names=()):
    return classify_event(title, show_names)["event_type"] == "performance"


def is_rehearsal(title, show_names=()):
    """Attendance eligibility depends on the event type, never a group label."""
    return classify_event(title, show_names)["event_type"] == "rehearsal"
