from bot.core.console_filters import (
    BUILTIN_EVENT_PATTERNS,
    BUILTIN_FILTER_PATTERNS,
    active_builtin_patterns,
    classify,
)


def test_active_builtin_patterns_excludes_disabled_keys():
    active = active_builtin_patterns(BUILTIN_FILTER_PATTERNS, {"map_points_saved"})

    assert BUILTIN_FILTER_PATTERNS["zdos_connections"] in active
    assert BUILTIN_FILTER_PATTERNS["map_points_saved"] not in active


def test_classify_suppresses_known_noise_in_blacklist_mode():
    outcome = classify(
        "Saved 6840 map points to disk.",
        filter_mode="blacklist",
        active_builtin_filters=list(BUILTIN_FILTER_PATTERNS.values()),
        custom_filter_patterns=[],
        active_builtin_events=list(BUILTIN_EVENT_PATTERNS.values()),
        custom_event_patterns=[],
    )

    assert outcome == "suppress"


def test_classify_passes_through_normal_console_lines():
    outcome = classify(
        "Day 12 started",
        filter_mode="blacklist",
        active_builtin_filters=list(BUILTIN_FILTER_PATTERNS.values()),
        custom_filter_patterns=[],
        active_builtin_events=list(BUILTIN_EVENT_PATTERNS.values()),
        custom_event_patterns=[],
    )

    assert outcome == "console"


def test_classify_routes_join_events_to_event_channel():
    outcome = classify(
        "Steve123 has joined the server",
        filter_mode="blacklist",
        active_builtin_filters=list(BUILTIN_FILTER_PATTERNS.values()),
        custom_filter_patterns=[],
        active_builtin_events=list(BUILTIN_EVENT_PATTERNS.values()),
        custom_event_patterns=[],
    )

    assert outcome == "event"


def test_classify_event_takes_precedence_over_filter_suppression():
    outcome = classify(
        "Steve123 has joined and saved 5 map points to disk",
        filter_mode="blacklist",
        active_builtin_filters=[r"map points to disk"],
        custom_filter_patterns=[],
        active_builtin_events=[r"has joined"],
        custom_event_patterns=[],
    )

    assert outcome == "event"


def test_classify_whitelist_mode_suppresses_without_custom_patterns():
    outcome = classify(
        "Anything at all",
        filter_mode="whitelist",
        active_builtin_filters=list(BUILTIN_FILTER_PATTERNS.values()),
        custom_filter_patterns=[],
        active_builtin_events=[],
        custom_event_patterns=[],
    )

    assert outcome == "suppress"


def test_classify_whitelist_mode_passes_matching_custom_pattern():
    outcome = classify(
        "IMPORTANT: server restarting soon",
        filter_mode="whitelist",
        active_builtin_filters=list(BUILTIN_FILTER_PATTERNS.values()),
        custom_filter_patterns=[r"^IMPORTANT:"],
        active_builtin_events=[],
        custom_event_patterns=[],
    )

    assert outcome == "console"


def test_classify_off_mode_never_suppresses():
    outcome = classify(
        "Saved 6840 map points to disk.",
        filter_mode="off",
        active_builtin_filters=list(BUILTIN_FILTER_PATTERNS.values()),
        custom_filter_patterns=[],
        active_builtin_events=[],
        custom_event_patterns=[],
    )

    assert outcome == "console"
