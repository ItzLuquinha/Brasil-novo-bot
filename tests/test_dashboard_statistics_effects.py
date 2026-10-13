from pathlib import Path


def test_statistics_requests_derive_loading_from_the_active_request_key():
    source = Path("web/src/pages/dashboard/StatisticsTab.jsx").read_text(encoding="utf-8")
    assert "const reportLoading = reportResult.key !== reportRequestKey" in source
    assert "const reportError = reportResult.key === reportRequestKey ? reportResult.error : null" in source
    assert "setReportLoading(" not in source
    assert "setChannelReportLoading(" not in source
    assert "if (!activeChannelId) return undefined" in source
    assert "if (!controller.signal.aborted) setReportResult" in source
    assert "if (!controller.signal.aborted) setChannelReportResult" in source


def test_guild_detail_endpoint_has_no_unreachable_duplicate_return():
    source = Path("api/routers/guilds.py").read_text(encoding="utf-8")
    start = source.index("async def get_guild(")
    end = source.index("@router.get(", start)
    block = source[start:end]
    assert block.count("return _guild_json(guild)") == 1
