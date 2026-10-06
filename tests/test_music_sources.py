"""Musik-Quellen: Abrufe nie ins interne Netz (auch nicht ueber Weiterleitungen)."""


async def test_redirect_into_internal_network_is_blocked(monkeypatch):
    """Eine oeffentliche Adresse, die ins Heimnetz weiterleitet: jedes Ziel wird geprueft."""
    import httpx
    import pytest

    from bot.cogs.music import sources

    async def check(url):
        if "10.0.0." in url:
            raise sources.SourceError("Adressen im internen Netz sind nicht erlaubt.")

    def handler(request):
        if request.url.host == "radio.example":
            return httpx.Response(302, headers={"location": "http://10.0.0.5/admin.m3u"})
        return httpx.Response(200, content=b"http://10.0.0.5/stream")

    real = httpx.AsyncClient
    monkeypatch.setattr(sources, "check_public_url", check)
    monkeypatch.setattr(sources.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(sources.SourceError, match="internen Netz"):
        await sources.resolve_stream_url("https://radio.example/live.m3u")
