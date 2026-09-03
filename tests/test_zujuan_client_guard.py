# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_zujuan_client_guard.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网 WAF 分级处置单测：
JS 挑战自动退回浏览器、人机验证转人工、429 指数退避、认不出的页面绝不当成空数据
"""
import asyncio

import pytest

import config
from media_platform.zujuan.client import MAX_RATE_LIMIT_RETRY, ZuJuanClient
from media_platform.zujuan.exception import (
    CaptchaPageError,
    ChallengePageError,
    DataFetchError,
    RateLimitError,
)

OK_HTML = '<html><body><div class="tk-quest-item" questionid="1"></div></body></html>'
CHALLENGE_HTML = '<html><body onload="check()"><input name="parm_0"></body></html>'
CAPTCHA_HTML = '<html><body><div id="nc-container"></div>滑动验证</body></html>'
PLAIN_HTML = "<html><body><p>本页没有题目</p></body></html>"


class DummyContext:
    async def cookies(self):
        return [{"name": "acw_sc__v2", "value": "solved"}]


class DummyPage:
    """按脚本依次吐出页面内容的假 Page"""

    def __init__(self, contents):
        self._contents = list(contents)
        self.context = DummyContext()
        self.goto_urls = []
        self.brought_to_front = False

    async def goto(self, url, **kwargs):
        self.goto_urls.append(url)

    async def content(self):
        if len(self._contents) > 1:
            return self._contents.pop(0)
        return self._contents[0]

    async def bring_to_front(self):
        self.brought_to_front = True


@pytest.fixture
def no_sleep(monkeypatch):
    """把 asyncio.sleep 换成记录调用的空实现，测试不真的等"""
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return delays


def make_client(page=None):
    client = ZuJuanClient(cookie_str="a=1", playwright_page=page)
    return client


@pytest.mark.asyncio
async def test_js_challenge_falls_back_to_browser(no_sleep):
    page = DummyPage([OK_HTML])
    client = make_client(page)

    async def fake_request(*args, **kwargs):
        raise ChallengePageError("challenged")

    client.request = fake_request

    html = await client.get_page_html("https://zujuan.xkw.com/gzsx/zsd28745/o2p2/")

    assert html == OK_HTML
    assert page.goto_urls == ["https://zujuan.xkw.com/gzsx/zsd28745/o2p2/"]
    # 浏览器过完挑战后的新凭证要同步回 httpx，后面的页才不用再走浏览器
    assert client.headers["Cookie"] == "acw_sc__v2=solved"


@pytest.mark.asyncio
async def test_captcha_from_httpx_hands_over_to_browser(no_sleep):
    page = DummyPage([OK_HTML])
    client = make_client(page)
    attempts = []

    async def fake_request(*args, **kwargs):
        attempts.append(1)
        raise CaptchaPageError("captcha")

    client.request = fake_request

    html = await client.get_page_html("https://zujuan.xkw.com/x")

    assert html == OK_HTML
    # 人机验证不该在 httpx 上重试，只会浪费额度并加重风控
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_rate_limit_backs_off_exponentially(no_sleep):
    client = make_client(DummyPage([OK_HTML]))
    calls = {"n": 0}

    async def fake_request(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError("429")
        return OK_HTML

    client.request = fake_request

    html = await client.get_page_html("https://zujuan.xkw.com/x")

    assert html == OK_HTML
    assert calls["n"] == 3
    # 5*2^0 和 5*2^1 打底，加上 0~2 秒抖动
    assert len(no_sleep) == 2
    assert 5 <= no_sleep[0] < 7
    assert 10 <= no_sleep[1] < 12


@pytest.mark.asyncio
async def test_rate_limit_exhausted_falls_back_to_browser(no_sleep):
    page = DummyPage([OK_HTML])
    client = make_client(page)
    calls = {"n": 0}

    async def fake_request(*args, **kwargs):
        calls["n"] += 1
        raise RateLimitError("429")

    client.request = fake_request

    html = await client.get_page_html("https://zujuan.xkw.com/x")

    assert calls["n"] == MAX_RATE_LIMIT_RETRY
    assert html == OK_HTML
    assert page.goto_urls == ["https://zujuan.xkw.com/x"]


@pytest.mark.asyncio
async def test_browser_captcha_waits_for_human(no_sleep, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_CDP_MODE", False)
    monkeypatch.setattr(config, "HEADLESS", False)
    monkeypatch.setattr(config, "ZUJUAN_ENABLE_HUMAN_SOLVE", True)
    # 先是验证码页，人过完之后变成正常页
    page = DummyPage([CAPTCHA_HTML, CAPTCHA_HTML, OK_HTML])
    client = make_client(page)

    html = await client.fetch_html_by_browser("https://zujuan.xkw.com/x")

    assert html == OK_HTML
    assert page.brought_to_front is True
    assert client.headers["Cookie"] == "acw_sc__v2=solved"


@pytest.mark.asyncio
async def test_human_solve_refused_in_headless_mode(no_sleep, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_CDP_MODE", False)
    monkeypatch.setattr(config, "HEADLESS", True)
    client = make_client(DummyPage([CAPTCHA_HTML]))

    with pytest.raises(DataFetchError, match="无头模式"):
        await client.fetch_html_by_browser("https://zujuan.xkw.com/x")


@pytest.mark.asyncio
async def test_human_solve_can_be_disabled(no_sleep, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_CDP_MODE", False)
    monkeypatch.setattr(config, "HEADLESS", False)
    monkeypatch.setattr(config, "ZUJUAN_ENABLE_HUMAN_SOLVE", False)
    client = make_client(DummyPage([CAPTCHA_HTML]))

    with pytest.raises(DataFetchError, match="ZUJUAN_ENABLE_HUMAN_SOLVE"):
        await client.fetch_html_by_browser("https://zujuan.xkw.com/x")


@pytest.mark.asyncio
async def test_human_solve_times_out(no_sleep, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_CDP_MODE", False)
    monkeypatch.setattr(config, "HEADLESS", False)
    monkeypatch.setattr(config, "ZUJUAN_ENABLE_HUMAN_SOLVE", True)
    monkeypatch.setattr(config, "ZUJUAN_HUMAN_SOLVE_TIMEOUT", 3)
    client = make_client(DummyPage([CAPTCHA_HTML]))

    with pytest.raises(DataFetchError, match="人机验证等待超时"):
        await client.fetch_html_by_browser("https://zujuan.xkw.com/x")


@pytest.mark.asyncio
async def test_browser_still_challenged_raises(no_sleep):
    # 浏览器也过不去挑战，宁可报错也不能把挑战页当成空数据写下去
    client = make_client(DummyPage([CHALLENGE_HTML]))

    with pytest.raises(DataFetchError, match="still blocked"):
        await client.fetch_html_by_browser("https://zujuan.xkw.com/x")


@pytest.mark.asyncio
async def test_browser_unknown_page_treated_as_empty(no_sleep):
    # 浏览器带着真实会话都没看到题、也没有拦截特征，那就是这页本来没题，交给上层自然停止
    client = make_client(DummyPage([PLAIN_HTML]))

    html = await client.fetch_html_by_browser("https://zujuan.xkw.com/x")

    assert html == PLAIN_HTML
