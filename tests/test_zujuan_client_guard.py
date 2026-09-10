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
    """假浏览器上下文。★ 记下 cookies() 是不是带着域过滤调的 —— 不带 urls 会把
    用户真实 Chrome 里所有域的 Cookie 一起发给组卷网"""

    def __init__(self):
        self.cookies_called_with = []

    async def cookies(self, urls=None):
        self.cookies_called_with.append(urls)
        allcookies = [
            {"name": "acw_sc__v2", "value": "solved"},
            {"name": "OTHER_SITE_SESSION", "value": "leak"},
        ]
        if urls:
            return allcookies[:1]
        return allcookies


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


@pytest.fixture(autouse=True)
def pinned_zujuan_config():
    """★ 把 zujuan 的开关钉到已知值再跑。

    这些开关是给人调的（比如把 ZUJUAN_FETCH_MODE 改成 browser 来对付风控），
    测试直接读实盘 config 就会被用户的正常配置改动搞挂 —— 挂了还容易被误以为
    是代码坏了。
    """
    knobs = {
        "ZUJUAN_FETCH_MODE": "hybrid",
        "ZUJUAN_HUMAN_PAGING": True,
        "ZUJUAN_ENABLE_HUMAN_SOLVE": True,
        "ZUJUAN_HUMAN_SOLVE_TIMEOUT": 5,
    }
    saved = {name: getattr(config, name, None) for name in knobs}
    for name, value in knobs.items():
        setattr(config, name, value)
    yield
    for name, value in saved.items():
        setattr(config, name, value)


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


# ---------------------------------------------------------------------------
# WAF 凭证要能在浏览器和 httpx 之间传下去
#
# "人手动过一次滑块就好了，脚本每翻一页都要再过一次"这个故障的三个成因，
# 每个都在这里钉一条测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cookies_are_synced_scoped_to_zujuan_domain(no_sleep):
    """★ 只同步组卷网这个域的 Cookie，不能把用户其它网站的登录态一起发出去"""
    page = DummyPage([OK_HTML])
    client = make_client(page)

    await client.fetch_html_by_browser("https://zujuan.xkw.com/x")

    assert page.context.cookies_called_with == [["https://zujuan.xkw.com"]]
    assert "OTHER_SITE_SESSION" not in client.headers["Cookie"]
    assert client.headers["Cookie"] == "acw_sc__v2=solved"
    await client.close()


@pytest.mark.asyncio
async def test_httpx_uses_the_user_agent_it_was_given(no_sleep):
    """★ httpx 必须用过验证那个浏览器的真实 UA，不能自己随机挑一个 ——
    WAF 把凭证绑在指纹上，换 UA 用同一张凭证会被判成盗用并立刻重新验证"""
    real_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0.0.0 Safari/537.36"
    client = ZuJuanClient(user_agent=real_ua)
    assert client.headers["User-Agent"] == real_ua
    # 顺带确认补上了浏览器才有的那几个头
    for header in ("Sec-Fetch-Mode", "Sec-Fetch-Dest", "Accept-Encoding"):
        assert header in client.headers
    await client.close()


def test_client_hints_come_from_the_page_not_from_guessing():
    """sec-ch-ua 用页面真实报的 brands 拼；取不到就不发（猜出来的比不发更像机器）"""
    from media_platform.zujuan.client import client_hints_from_page_data

    assert client_hints_from_page_data(None) == {}
    hints = client_hints_from_page_data(
        {
            "brands": [
                {"brand": "Not?A_Brand", "version": "24"},
                {"brand": "Chromium", "version": "141"},
            ],
            "mobile": False,
            "platform": "Windows",
        }
    )
    assert hints["sec-ch-ua"] == '"Not?A_Brand";v="24", "Chromium";v="141"'
    assert hints["sec-ch-ua-mobile"] == "?0"
    assert hints["sec-ch-ua-platform"] == '"Windows"'


@pytest.mark.asyncio
async def test_httpx_client_is_reused_so_set_cookie_survives(no_sleep):
    """★ client 必须长期存活，用完即弃会把每个响应的 Set-Cookie 全丢掉 ——
    WAF 的 acw_tc 几乎每个响应都轮换，丢了就等于一直在重放过期凭证"""
    client = make_client()
    first = await client._get_client()
    second = await client._get_client()
    assert first is second

    # jar 里的凭证要能存活到下一次请求
    first.cookies.set("acw_tc", "rotated", domain=".xkw.com")
    assert (await client._get_client()).cookies.get("acw_tc", domain=".xkw.com") == "rotated"
    await client.close()


@pytest.mark.asyncio
async def test_proxy_change_rebuilds_client_but_keeps_cookies(no_sleep):
    """换代理不代表凭证失效，Cookie jar 要带过去"""
    client = make_client()
    old = await client._get_client()
    old.cookies.set("acw_sc__v2", "solved")

    client.proxy = "http://127.0.0.1:8888"
    new = await client._get_client()

    assert new is not old
    assert new.cookies.get("acw_sc__v2") == "solved"
    await client.close()


@pytest.mark.asyncio
async def test_human_solve_enters_browser_cooldown(no_sleep):
    """★ 人刚过完验证时 WAF 对这个 IP 高度戒备，立刻用 httpx 打过去会再次触发。
    过完验证要进入一段只走浏览器的冷却期，否则就变成每页都弹滑块"""
    page = DummyPage([CAPTCHA_HTML, OK_HTML])
    client = make_client(page)
    assert client._in_browser_cooldown() is False

    await client.fetch_html_by_browser("https://zujuan.xkw.com/x")

    assert client._in_browser_cooldown() is True
    await client.close()


@pytest.mark.asyncio
async def test_cooldown_short_circuits_httpx(no_sleep):
    """冷却期内直接走浏览器，连试都不试 httpx"""
    page = DummyPage([OK_HTML])
    client = make_client(page)
    tried = []

    async def fake_request(*args, **kwargs):
        tried.append(1)
        raise AssertionError("冷却期内不该再打 httpx")

    client.request = fake_request
    client._enter_browser_cooldown("测试")

    html = await client.get_page_html("https://zujuan.xkw.com/x")
    assert html == OK_HTML
    assert tried == []
    await client.close()


@pytest.mark.asyncio
async def test_cooldown_backs_off_then_resets_on_success(no_sleep):
    """连续被挑战时冷却指数增长；httpx 一旦恢复正常立刻解除"""
    client = make_client()
    client._enter_browser_cooldown("第一次")
    first = client._browser_only_until
    client._enter_browser_cooldown("第二次")
    assert client._browser_only_until > first
    assert client._challenge_streak == 2

    client._reset_browser_cooldown()
    assert client._challenge_streak == 0
    assert client._in_browser_cooldown() is False
    await client.close()


def test_accept_encoding_only_advertises_what_httpx_can_decode():
    """★ 不能照抄 Chrome 写 br —— 没装 brotli 还声明，服务端真返回 br 时
    httpx 解不开，拿到二进制乱码会被误判成 UNKNOWN 甚至空页"""
    from httpx._decoders import SUPPORTED_DECODERS

    from media_platform.zujuan.client import build_browser_like_headers

    advertised = build_browser_like_headers("UA")["Accept-Encoding"]
    for encoding in advertised.split(","):
        assert encoding.strip() in SUPPORTED_DECODERS


# ---------------------------------------------------------------------------
# 点击分页器翻页
#
# 直接 goto 深链接等于往地址栏连续粘贴几百个 URL，点分页器才是站点期望的路径。
# 但点击最大的风险是**点错链接却不报错**，所以每条测试都围着"页码能不能确认"转
# ---------------------------------------------------------------------------

# 照线上真实结构写的分页器（2026-09 实测）：当前页是带 data-num 的 a.active，
# "下一页"是个没有文本的图标按钮，末尾还有个跳转输入框
PAGER_TPL = (
    '<div class="tk-pager" data-sum="250" data-size="10" data-cap="10">'
    '<a data-num="{current}" data-type="switchPage" class="pager-item page-num active">{current}</a>'
    '<a data-type="switchPage" data-num="2" class="pager-item page-num" data-href="/czsx/zsd1/o2p2/"> 2</a>'
    '<a data-type="switchPage" data-num="3" class="pager-item page-num" data-href="/czsx/zsd1/o2p3/"> 3</a>'
    '<a title="下一页" data-type="nextPage" class="pager-item next-page"></a>'
    '<a id="lastpage" data-type="lastPage" lastid="25" class="pager-item to-last">末页</a>'
    '<div class="go-to"><input class="go-to__page" id="iptGotoNum" type="text" value="1">'
    '<a data-type="confirmGoto" class="confirm-btn" title="确定跳转">确定</a></div>'
    "</div>"
)


def list_page_html(current, first_qid):
    return (
        f'<div class="tk-quest-item" questionid="{first_qid}">题</div>'
        + PAGER_TPL.format(current=current)
    )


class FakeLocator:
    def __init__(self, found=True, on_click=None, selector=""):
        self._found = found
        self._on_click = on_click
        self.selector = selector
        self.clicked = False
        self.scrolled = False
        self.filled = None

    @property
    def first(self):
        return self

    async def count(self):
        return 1 if self._found else 0

    async def is_visible(self):
        return self._found

    async def scroll_into_view_if_needed(self, timeout=None):
        self.scrolled = True

    async def fill(self, value):
        self.filled = value

    async def click(self, timeout=None):
        self.clicked = True
        if self._on_click:
            self._on_click()


class ClickablePage:
    """能点分页器的假 Page：点一下就把 content() 换成下一页"""

    def __init__(self, pages, url="https://zujuan.xkw.com/czsx/zsd1/o2/", link_found=True):
        self._pages = list(pages)
        self._index = 0
        self.url = url
        self.context = DummyContext()
        self.goto_urls = []
        self.brought_to_front = False
        self.locator_calls = []
        self.used_locators = []
        self._link_found = link_found

    def _advance(self):
        if self._index < len(self._pages) - 1:
            self._index += 1

    def locator(self, selector):
        self.locator_calls.append(selector)
        found = self._link_found
        if callable(self._link_found):
            found = self._link_found(selector)
        loc = FakeLocator(found=found, on_click=self._advance, selector=selector)
        if found:
            self.used_locators.append(loc)
        return loc

    async def content(self):
        return self._pages[self._index]

    async def goto(self, url, **kwargs):
        self.goto_urls.append(url)
        self._index = len(self._pages) - 1

    async def bring_to_front(self):
        self.brought_to_front = True


@pytest.mark.asyncio
async def test_click_paging_is_used_instead_of_goto(no_sleep):
    """分页器上有目标页链接、点完页码也对得上 —— 走点击，不 goto"""
    page = ClickablePage([list_page_html(1, "1001"), list_page_html(2, "2002")])
    client = make_client(page)
    client._browser_base_url = "https://zujuan.xkw.com/czsx/zsd1/o2/"
    client._browser_page_no = 1

    html = await client._navigate(
        "https://zujuan.xkw.com/czsx/zsd1/o2p2/",
        page_no=2,
        base_url="https://zujuan.xkw.com/czsx/zsd1/o2/",
    )

    assert "2002" in html
    assert page.goto_urls == []          # ★ 没有走 goto
    assert client._browser_page_no == 2
    await client.close()


@pytest.mark.asyncio
async def test_falls_back_to_goto_when_page_number_cannot_be_confirmed(no_sleep):
    """★ 内容确实换了，但分页器和 URL 都证明不了这是第 2 页 —— 必须退回 goto。
    点错链接却当成第 N 页入库并记进度，是不报错的静默数据损坏"""
    unconfirmable = '<div class="tk-quest-item" questionid="9999">题</div><div class="tk-pager"><a>x</a></div>'
    page = ClickablePage([list_page_html(1, "1001"), unconfirmable])
    client = make_client(page)
    client._browser_base_url = "https://zujuan.xkw.com/czsx/zsd1/o2/"
    client._browser_page_no = 1

    result = await client._try_click_paging(2, "https://zujuan.xkw.com/czsx/zsd1/o2/")

    assert result is None                # 不敢用这份 HTML
    await client.close()


@pytest.mark.asyncio
async def test_falls_back_to_goto_when_pager_link_missing(no_sleep):
    """分页器里找不到目标页的链接（翻得太远、或站点改版），退回 goto"""
    page = ClickablePage([list_page_html(1, "1001")], link_found=False)
    client = make_client(page)
    client._browser_base_url = "https://zujuan.xkw.com/czsx/zsd1/o2/"
    client._browser_page_no = 1

    html = await client._navigate(
        "https://zujuan.xkw.com/czsx/zsd1/o2p387/",
        page_no=387,
        base_url="https://zujuan.xkw.com/czsx/zsd1/o2/",
    )

    assert page.goto_urls == ["https://zujuan.xkw.com/czsx/zsd1/o2p387/"]
    assert "1001" in html
    await client.close()


@pytest.mark.asyncio
async def test_no_click_when_switching_to_a_different_slice(no_sleep):
    """换了一片（筛选条件变了），分页器上的链接指向的是上一片，只能 goto"""
    page = ClickablePage([list_page_html(1, "1001")])
    client = make_client(page)
    client._browser_base_url = "https://zujuan.xkw.com/czsx/zsd1/qt1101o2/"
    client._browser_page_no = 5

    await client._navigate(
        "https://zujuan.xkw.com/czsx/zsd1/qt1102o2p2/",
        page_no=2,
        base_url="https://zujuan.xkw.com/czsx/zsd1/qt1102o2/",
    )

    assert page.goto_urls == ["https://zujuan.xkw.com/czsx/zsd1/qt1102o2p2/"]
    await client.close()


@pytest.mark.asyncio
async def test_human_paging_can_be_switched_off(no_sleep):
    """ZUJUAN_HUMAN_PAGING=False 时一律 goto"""
    page = ClickablePage([list_page_html(1, "1001"), list_page_html(2, "2002")])
    client = make_client(page)
    client._browser_base_url = "https://zujuan.xkw.com/czsx/zsd1/o2/"
    client._browser_page_no = 1

    original = getattr(config, "ZUJUAN_HUMAN_PAGING", True)
    config.ZUJUAN_HUMAN_PAGING = False
    try:
        await client._navigate(
            "https://zujuan.xkw.com/czsx/zsd1/o2p2/",
            page_no=2,
            base_url="https://zujuan.xkw.com/czsx/zsd1/o2/",
        )
    finally:
        config.ZUJUAN_HUMAN_PAGING = original

    assert page.goto_urls == ["https://zujuan.xkw.com/czsx/zsd1/o2p2/"]
    await client.close()


@pytest.mark.asyncio
async def test_captcha_during_click_paging_is_still_detected(no_sleep):
    """点着点着翻出个验证页，也要按风控层级正常处置，不能当成'内容换了'"""
    page = ClickablePage([list_page_html(1, "1001"), CAPTCHA_HTML])
    client = make_client(page)
    client._browser_base_url = "https://zujuan.xkw.com/czsx/zsd1/o2/"
    client._browser_page_no = 1

    result = await client._try_click_paging(2, "https://zujuan.xkw.com/czsx/zsd1/o2/")

    # 拿不到可确认的第 2 页 -> 返回 None 退回 goto，由 fetch_html_by_browser 走验证流程
    assert result is None
    await client.close()


@pytest.mark.asyncio
async def test_position_is_forgotten_after_human_solve(no_sleep):
    """★ 过验证过程中页面跳转过，浏览器停在哪已经不可信，必须清掉
    否则下一次会以为还停在原来那一页，点出错误的页码"""
    page = DummyPage([CAPTCHA_HTML, OK_HTML])
    client = make_client(page)
    client._browser_base_url = "https://zujuan.xkw.com/czsx/zsd1/o2/"
    client._browser_page_no = 7

    await client.fetch_html_by_browser("https://zujuan.xkw.com/x")

    assert client._browser_base_url is None
    assert client._browser_page_no is None
    await client.close()


def test_empty_list_page_is_ok_not_unknown():
    """★ 题量为 0 的知识点页面没有卡片，但有"共计 N 道试题" —— 这是真实列表页，
    不能和被拦截的页面混为一谈，否则空知识点的 site_total 永远记不下来"""
    from media_platform.zujuan.help import PageStatus, page_status

    empty_list = '<em class="ques-sum" id="questioncount">0</em><p>暂无试题</p>'
    assert page_status(empty_list) is PageStatus.OK


def test_blocked_page_without_questioncount_is_still_not_ok():
    """加了新标记之后，拦截页仍然要被认出来 —— 这条不能被上面那条放松掉"""
    from media_platform.zujuan.help import PageStatus, page_status

    assert page_status(CAPTCHA_HTML) is PageStatus.CAPTCHA
    assert page_status(CHALLENGE_HTML) is PageStatus.JS_CHALLENGE
    assert page_status("<html><body>什么都没有</body></html>") is PageStatus.UNKNOWN


# ---------------------------------------------------------------------------
# 分页器控件定位（按 2026-09 线上真实 DOM）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pager_link_prefers_data_num(no_sleep):
    """页码链接优先用 data-num 定位 —— 页码就在属性里，不用从 data-href 里抠"""
    page = ClickablePage([list_page_html(1, "1001")])
    client = make_client(page)
    client._browser_page_no = 1

    await client._find_pager_link(2)

    assert page.locator_calls[0] == (
        'div.tk-pager a[data-type="switchPage"][data-num="2"]'
    )
    await client.close()


@pytest.mark.asyncio
async def test_next_page_button_is_found_by_attribute_not_text(no_sleep):
    """★ "下一页"是个没有文本的图标按钮：<a title="下一页" data-type="nextPage"></a>
    :has-text("下一页") 永远匹配不到它，只能靠 data-type / title / class"""
    def only_next(selector):
        return "nextPage" in selector

    page = ClickablePage([list_page_html(1, "1001")], link_found=only_next)
    client = make_client(page)
    client._browser_page_no = 5

    link = await client._find_pager_link(6)      # 正好是下一页

    assert link is not None
    assert 'data-type="nextPage"' in link.selector
    # 不是下一页时不能拿"下一页"按钮凑数
    client._browser_page_no = 5
    assert await client._find_pager_link(50) is None
    await client.close()


@pytest.mark.asyncio
async def test_far_page_uses_the_pager_jump_box(no_sleep):
    """★ 分页器 data-cap=10，一次只显示 10 个页码。要到第 387 页，
    页码链接和"下一页"都不行，只能用站点自带的跳转输入框"""
    def only_goto(selector):
        return "iptGotoNum" in selector or "confirmGoto" in selector

    page = ClickablePage([list_page_html(1, "1001")], link_found=only_goto)
    client = make_client(page)
    client._browser_page_no = 1

    assert await client._find_pager_link(387) is None      # 页码链接找不到
    assert await client._jump_via_input(387) is True

    box = next(l for l in page.used_locators if "iptGotoNum" in l.selector)
    button = next(l for l in page.used_locators if "confirmGoto" in l.selector)
    assert box.filled == "387"                              # 填了页码
    assert button.clicked is True                           # 点了确定
    await client.close()


@pytest.mark.asyncio
async def test_jump_box_missing_reports_false(no_sleep):
    """跳转框也没有时如实返回 False，让调用方退回 goto"""
    page = ClickablePage([list_page_html(1, "1001")], link_found=False)
    client = make_client(page)
    assert await client._jump_via_input(387) is False
    await client.close()
