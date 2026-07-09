from bot.cogs.banner.cog import BACKOFF_BASE_SECONDS, BACKOFF_MAX_SECONDS, BannerCog


def _cog() -> BannerCog:
    return BannerCog(bot=None)


def test_fresh_target_is_not_skipped():
    cog = _cog()
    assert not cog._should_skip(("server", 1))


def test_failure_triggers_skip_until_backoff_elapses():
    cog = _cog()
    key = ("server", 1)

    cog._record_failure(key)

    assert cog._should_skip(key)
    assert cog._backoff_until[key] > 0


def test_repeated_failures_increase_backoff_exponentially():
    cog = _cog()
    key = ("server", 1)

    cog._record_failure(key)
    first_backoff = cog._backoff_until[key]
    cog._record_failure(key)
    second_backoff = cog._backoff_until[key]

    assert second_backoff > first_backoff


def test_backoff_is_capped_at_max():
    cog = _cog()
    key = ("server", 1)

    for _ in range(20):
        cog._record_failure(key)

    assert cog._failures[key] == 20
    # Der Backoff selbst darf trotz 20 Fehlschlaegen nicht ueber das Maximum steigen -
    # geprueft ueber die verstrichene Zeit bis zum gespeicherten Ziel-Zeitpunkt.
    import time

    remaining = cog._backoff_until[key] - time.monotonic()
    assert remaining <= BACKOFF_MAX_SECONDS + 1


def test_success_clears_failure_state():
    cog = _cog()
    key = ("server", 1)
    cog._record_failure(key)

    cog._record_success(key)

    assert not cog._should_skip(key)
    assert key not in cog._failures
    assert key not in cog._backoff_until


def test_base_backoff_matches_configured_constant():
    cog = _cog()
    key = ("server", 1)

    cog._record_failure(key)

    import time

    remaining = cog._backoff_until[key] - time.monotonic()
    assert BACKOFF_BASE_SECONDS - 1 <= remaining <= BACKOFF_BASE_SECONDS + 1
