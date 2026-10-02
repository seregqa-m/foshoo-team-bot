"""Event type tags and show names are independent parts of a calendar title."""
import re


EVENT_TYPES = {
    "спект": "performance",
    "спектакль": "performance",
    "реп": "rehearsal",
    "репетиция": "rehearsal",
}
SHOW_ALIASES = {"лг": "Любовь Громова"}


def _normalize(value):
    return " ".join((value or "").split()).casefold()


def classify_event(title, show_names=()):
    """Explicit recognized tags override the legacy inference from a show name.

    No I/O: callers can supply the current show catalog when it is available.
    Aliases match whole words, so ЛГ never matches inside another word.
    """
    title = title or ""
    event_type = next((EVENT_TYPES[tag] for raw in re.findall(r"\[([^\[\]]*)\]", title)
                       if (tag := _normalize(raw).rstrip(".")) in EVENT_TYPES), None)
    name_part = _normalize(re.sub(r"\[[^\[\]]*\]", " ", title))
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


def is_troupe_event(title, show_names=(), troupe_filter="труппа 1"):
    """Events eligible for troupe attendance, excluding performances."""
    classification = classify_event(title, show_names)
    if classification["event_type"] == "performance":
        return False
    title, troupe_filter = _normalize(title), _normalize(troupe_filter)
    if troupe_filter and troupe_filter in title:
        return True
    return bool(classification["event_type"] == "rehearsal" and classification["show_name"]
                and "труппа 2" not in title and "лаба" not in title)
