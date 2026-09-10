# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zujuan/client.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

import asyncio
import random
import re
import time
from typing import Dict, List, Optional

import httpx
from playwright.async_api import BrowserContext, Page
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

import config
from base.base_crawler import AbstractApiClient
from proxy.proxy_mixin import ProxyRefreshMixin
from tools import utils
from tools.httpx_util import make_async_client

from .exception import (
    CaptchaPageError,
    ChallengePageError,
    DataFetchError,
    RateLimitError,
)
from .help import (
    ZUJUAN_HOST,
    PageStatus,
    current_page_from_pager,
    dump_pager_html,
    first_question_id,
    page_status,
)

# 被限流时的退避次数，参照 kuaishou 的做法用指数退避 + 抖动
MAX_RATE_LIMIT_RETRY = 3

# httpx 被挑战/被验证之后，先让浏览器顶一段时间的基础冷却秒数
BROWSER_COOLDOWN_BASE_SEC = 60

# 冷却上限，连续被挑战时按 2 的幂增长但不超过这个值
BROWSER_COOLDOWN_MAX_SEC = 600

CHROME_VERSION_RE = re.compile(r"Chrome/(\d+)")

# 点击翻页后等内容真的换掉的最长秒数
CLICK_PAGING_TIMEOUT_SEC = 20

# goto 之后等题目卡片进 DOM 的最长毫秒数。
# ★ domcontentloaded 只保证 HTML 骨架到位，题目列表是随后由 JS 填进去的；
#   立刻 page.content() 会拿到一个"有 #questioncount、零张卡片"的半成品，
#   它照样能通过 page_status() 和 extract_site_total()，上层会误判成"翻到底了"
LIST_RENDER_TIMEOUT_MS = 15000


def supported_accept_encoding() -> str:
    """
    只声明 httpx **真的能解**的压缩方式。

    ★ 别照着 Chrome 硬写 "gzip, deflate, br"：brotli 要装 brotli/brotlicffi 才能
      解，没装还去声明，服务端一旦真的返回 br，httpx 解不开 —— 拿到的是二进制
      乱码，page_status() 匹配不到任何特征，会被判成 UNKNOWN 白白退回浏览器，
      更糟的情况是被当成空页。宁可少声明一种压缩，也不能声明了解不开。
    """
    from httpx._decoders import SUPPORTED_DECODERS

    encodings = [name for name in SUPPORTED_DECODERS if name != "identity"]
    return ", ".join(encodings) if encodings else "identity"


def build_browser_like_headers(
    user_agent: str,
    client_hints: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """
    拼一套尽量贴近 Chrome 的请求头。

    ★ 这里的 User-Agent 必须和**过验证的那个浏览器**完全一致。阿里云 WAF 把过完
      滑块发的凭证绑在客户端指纹（UA + IP 起步）上，换一个 UA 去用同一张凭证，
      WAF 会判定凭证被盗用并立刻重新验证 —— 表现就是"人过完验证，下一页又弹"。
    """
    headers = {
        "User-Agent": user_agent,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": supported_accept_encoding(),
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Referer": ZUJUAN_HOST,
    }
    if client_hints:
        headers.update(client_hints)
    return headers


def client_hints_from_page_data(ua_data: Optional[Dict]) -> Dict[str, str]:
    """
    把浏览器里 navigator.userAgentData 的原样内容翻成 sec-ch-ua 系列请求头。

    ★ 用页面真实报的 brands 拼，而不是照 UA 里的版本号硬编一套 —— Chrome 的
      品牌列表里有一项是每个版本都变的 GREASE 值，猜出来的和真实值对不上，
      比不发这个头更像机器。取不到就干脆不发。
    """
    if not ua_data:
        return {}
    brands = ua_data.get("brands") or []
    parts = []
    for brand in brands:
        name = (brand or {}).get("brand")
        version = (brand or {}).get("version")
        if name and version:
            parts.append(f'"{name}";v="{version}"')
    hints: Dict[str, str] = {}
    if parts:
        hints["sec-ch-ua"] = ", ".join(parts)
    if "mobile" in ua_data:
        hints["sec-ch-ua-mobile"] = "?1" if ua_data.get("mobile") else "?0"
    platform = ua_data.get("platform")
    if platform:
        hints["sec-ch-ua-platform"] = f'"{platform}"'
    return hints


class ZuJuanClient(AbstractApiClient, ProxyRefreshMixin):
    """
    组卷网页面客户端。

    组卷网在 CDN 层挂了阿里云 WAF，直接用 httpx 请求只会拿到一段挑战脚本。所以
    流程是：先用浏览器打开一次首页让挑战自行通过，把 Cookie 交给 httpx 翻页；
    httpx 被拦下就退回浏览器。

    要让"浏览器过验证 + httpx 翻页"这套真的成立，httpx 必须尽可能装得和那个
    浏览器是同一个客户端，否则凭证一到 httpx 手里就失效。三件事缺一不可：

    1. **同一个 User-Agent** —— 用浏览器页面里真实的 ``navigator.userAgent``，
       不能用随机假 UA（CDP 接管真实 Chrome 时 Playwright 的 user_agent 参数
       是被忽略的，浏览器用的始终是它自己的真 UA）
    2. **持久的 Cookie jar** —— WAF 的 acw_tc 几乎每个响应都轮换，client 用完
       即弃会把 Set-Cookie 全丢掉，等于一直在重放过期凭证
    3. **只带本域 Cookie** —— 从浏览器同步时必须按域过滤，否则会把用户其它
       网站的 Cookie 一起发给组卷网

    阿里云 WAF 是阶梯式升级的，按 :class:`PageStatus` 分级处置：

    - ``JS_CHALLENGE`` —— 退回浏览器自动过，过完把新 Cookie 同步回 httpx
    - ``CAPTCHA``（滑块/点选）—— 停下来把页面推到人眼前，等人过完再继续，
      并进入一段"只用浏览器"的冷却期
    - ``429`` 限流 —— 指数退避重试
    - ``UNKNOWN`` —— 认不出来一律当失败，绝不当成空数据
    """

    def __init__(
        self,
        timeout: int = 30,
        user_agent: Optional[str] = None,
        cookie_str: str = "",
        proxy: Optional[str] = None,
        playwright_page: Optional[Page] = None,
        client_hints: Optional[Dict[str, str]] = None,
    ):
        self.timeout = timeout
        self.proxy = proxy
        self.playwright_page = playwright_page
        self._host = ZUJUAN_HOST
        self.user_agent = user_agent or utils.get_user_agent()
        self.headers = build_browser_like_headers(self.user_agent, client_hints)
        if cookie_str:
            self.headers["Cookie"] = cookie_str

        # 长生命周期 client：WAF 的 acw_tc 每个响应都可能轮换，必须让 httpx
        # 自己维护 Cookie jar 把 Set-Cookie 收下来
        self._client: Optional[httpx.AsyncClient] = None
        self._client_proxy: Optional[str] = None

        # 被挑战后的"只走浏览器"冷却，单调时钟
        self._browser_only_until: float = 0.0
        self._challenge_streak: int = 0

        # 浏览器标签页当前停在哪个列表页 —— 点击翻页要靠它判断能不能接着点
        self._browser_base_url: Optional[str] = None
        self._browser_page_no: Optional[int] = None
        self._pager_dumped = False

    # ------------------------------------------------------------------
    # httpx 客户端与 Cookie
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """拿到长生命周期的 client；代理换了才重建，并把 Cookie jar 带过去"""
        if self._client is not None and self._client_proxy == self.proxy:
            return self._client

        old_cookies = self._client.cookies if self._client is not None else None
        if self._client is not None:
            await self._client.aclose()

        self._client = make_async_client(proxy=self.proxy, follow_redirects=True)
        self._client_proxy = self.proxy
        if old_cookies is not None:
            # 代理换了不代表凭证失效，jar 要接着用
            for name, value in old_cookies.items():
                self._client.cookies.set(name, value)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def update_cookies(self, browser_context: BrowserContext):
        """
        把浏览器里组卷网这个域的 Cookie 同步到 httpx。

        ★ 必须按域过滤：不带 urls 参数时 Playwright 会返回整个浏览器上下文里
          **所有域**的 Cookie。CDP 接管的是用户真实的 Chrome，那样会把用户其它
          网站的登录态一起发给组卷网 —— 既是隐私泄露，几十 KB 的 Cookie 头本身
          也是个明显的异常特征
        """
        cookies = await browser_context.cookies(urls=[self._host])
        cookie_str, cookie_dict = utils.convert_cookies(cookies)
        self.headers["Cookie"] = cookie_str

        client = await self._get_client()
        for name, value in cookie_dict.items():
            client.cookies.set(name, value, domain=".xkw.com")
        return cookie_str, cookie_dict

    # ------------------------------------------------------------------
    # 请求
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def request(self, method: str, url: str, **kwargs) -> str:
        """
        发起 HTTP 请求并返回页面 HTML 文本。

        只对网络层抖动做重试：被挑战/被验证时用同一份 Cookie 再请求几次毫无意义，
        直接抛给上层去决定是退回浏览器还是等人工。
        """
        await self._refresh_proxy_if_expired()
        headers = kwargs.pop("headers", self.headers)
        # Cookie 交给 jar 管，头里那份只是给浏览器同步用的快照，别覆盖 jar
        headers = {k: v for k, v in headers.items() if k.lower() != "cookie"}

        client = await self._get_client()
        response = await client.request(method, url, timeout=self.timeout, headers=headers, **kwargs)

        if response.status_code == 429:
            raise RateLimitError(f"[ZuJuanClient.request] rate limited by HTTP 429, url: {url}")
        if response.status_code in (401, 403):
            raise DataFetchError(
                f"[ZuJuanClient.request] blocked with HTTP {response.status_code}, url: {url}"
            )
        if response.status_code != 200:
            raise DataFetchError(
                f"[ZuJuanClient.request] unexpected HTTP {response.status_code}, url: {url}"
            )

        status = page_status(response.text)
        if status is PageStatus.CAPTCHA:
            raise CaptchaPageError(f"[ZuJuanClient.request] hit WAF captcha page, url: {url}")
        if status is not PageStatus.OK:
            # JS 挑战页，或者认不出来的页面 —— 都交给浏览器再取一次，由它给出权威结果
            raise ChallengePageError(
                f"[ZuJuanClient.request] no question data (status: {status.value}), url: {url}"
            )
        return response.text

    def _in_browser_cooldown(self) -> bool:
        return time.monotonic() < self._browser_only_until

    def _enter_browser_cooldown(self, reason: str) -> None:
        """
        httpx 被拦下之后，先让浏览器顶一段时间。

        httpx 和 Chrome 的 TLS 指纹本来就不一样，WAF 一旦对这个 IP 提高了戒备，
        继续用 httpx 硬打只会把等级越推越高，最后变成"每页都要人拖滑块"。退回
        浏览器一段时间让凭证稳下来，比原地重试划算得多。
        """
        self._challenge_streak += 1
        seconds = min(
            BROWSER_COOLDOWN_BASE_SEC * (2 ** (self._challenge_streak - 1)),
            BROWSER_COOLDOWN_MAX_SEC,
        )
        self._browser_only_until = time.monotonic() + seconds
        utils.logger.warning(
            f"[ZuJuanClient] {reason}，接下来 {seconds}s 只走浏览器"
            f"（连续第 {self._challenge_streak} 次）"
        )

    def _reset_browser_cooldown(self) -> None:
        if self._challenge_streak:
            utils.logger.info("[ZuJuanClient] httpx 恢复正常，解除浏览器冷却")
        self._challenge_streak = 0
        self._browser_only_until = 0.0

    async def get_page_html(
        self,
        url: str,
        referer: str = "",
        page_no: Optional[int] = None,
        base_url: str = "",
    ) -> str:
        """
        取一个页面的 HTML。

        Args:
            url: 目标页完整 URL
            referer: 上一页 URL
            page_no: 目标页码；给了就允许用"点分页器"的方式翻页
            base_url: 这一片的首页 URL，判断能不能接着点分页器要用
        """
        mode = getattr(config, "ZUJUAN_FETCH_MODE", "hybrid")
        if mode == "browser":
            return await self.fetch_html_by_browser(url, page_no=page_no, base_url=base_url)

        if self._in_browser_cooldown():
            remaining = int(self._browser_only_until - time.monotonic())
            utils.logger.info(f"[ZuJuanClient] 处于浏览器冷却期（剩 {remaining}s），直接用浏览器取")
            return await self.fetch_html_by_browser(url, page_no=page_no, base_url=base_url)

        headers = dict(self.headers)
        if referer:
            headers["Referer"] = referer

        for attempt in range(MAX_RATE_LIMIT_RETRY):
            try:
                page_html = await self.request("GET", url, headers=headers)
                self._reset_browser_cooldown()
                return page_html
            except RateLimitError as e:
                if attempt >= MAX_RATE_LIMIT_RETRY - 1:
                    self._enter_browser_cooldown(f"httpx 连续 {MAX_RATE_LIMIT_RETRY} 次被限流({e})")
                    break
                delay = 5 * (2**attempt) + random.uniform(0, 2)
                utils.logger.warning(
                    f"[ZuJuanClient.get_page_html] rate limited on {url}, retry in {delay:.1f}s, "
                    f"attempt {attempt + 1}/{MAX_RATE_LIMIT_RETRY}"
                )
                await asyncio.sleep(delay)
            except CaptchaPageError:
                self._enter_browser_cooldown("httpx 撞上人机验证")
                break
            except ChallengePageError:
                self._enter_browser_cooldown("httpx 拿不到题目数据")
                break
            except Exception as e:
                utils.logger.warning(
                    f"[ZuJuanClient.get_page_html] httpx request failed ({e}), fallback to browser: {url}"
                )
                break

        return await self.fetch_html_by_browser(url, page_no=page_no, base_url=base_url)

    async def fetch_html_by_browser(
        self, url: str, page_no: Optional[int] = None, base_url: str = ""
    ) -> str:
        """
        用浏览器打开页面并返回渲染后的 HTML。

        浏览器这一趟的结果是权威的：它带着真实指纹和完整会话，如果它都没看到题目
        又没有任何拦截特征，那就是这一页本来就没题（比如翻过了最后一页），交给上层
        自然停止；只有确实被拦截时才报错或转人工。
        """
        if not self.playwright_page:
            raise DataFetchError("[ZuJuanClient.fetch_html_by_browser] playwright page is not available")

        page_html = await self._navigate(url, page_no=page_no, base_url=base_url)
        status = page_status(page_html)

        if status is PageStatus.JS_CHALLENGE:
            # 挑战页会自己 reload，给它一点时间再取一次
            await asyncio.sleep(3)
            page_html = await self.playwright_page.content()
            status = page_status(page_html)

        if status is PageStatus.CAPTCHA:
            page_html = await self.wait_human_solve(url)
            status = page_status(page_html)

        if status in (PageStatus.JS_CHALLENGE, PageStatus.CAPTCHA):
            raise DataFetchError(
                f"[ZuJuanClient.fetch_html_by_browser] still blocked (status: {status.value}), url: {url}"
            )
        if status is PageStatus.UNKNOWN:
            utils.logger.warning(
                f"[ZuJuanClient.fetch_html_by_browser] browser saw no question data and no block marker, "
                f"treat as empty page: {url}"
            )

        # 浏览器这一趟可能刷新了凭证，同步回 httpx，后面的页就不用再走浏览器
        await self._sync_cookies_from_page()
        return page_html

    async def _navigate(
        self, url: str, page_no: Optional[int] = None, base_url: str = ""
    ) -> str:
        """
        把浏览器带到目标页，优先用"点分页器"而不是直接 goto 深链接。

        直接 goto 一个 /o2p387/ 这样的深链接，等于有人往地址栏里连续粘贴几百个
        深链接：没有导航链、不触发站点自己的翻页 JS。点分页器则是站点本来就期望
        的那条路径，会话状态和真人翻页一致。
        """
        if getattr(config, "ZUJUAN_HUMAN_PAGING", True) and page_no:
            clicked_html = await self._try_click_paging(page_no, base_url)
            if clicked_html is not None:
                return clicked_html

        await self.playwright_page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await self._wait_for_list_rendered()
        page_html = await self.playwright_page.content()
        self._remember_position(page_html, url, page_no, base_url)
        return page_html

    async def _wait_for_list_rendered(self) -> None:
        """等题目卡片真的进了 DOM 再读 HTML。

        网慢的时候 goto 的 domcontentloaded 早于列表渲染，取早了拿到的是一个
        "有 #questioncount、零张卡片"的半成品 —— 这种页面 page_status() 判 OK、
        site_total 也读得到，上层会当成"这一页没题 = 翻到底了"，把一个才翻了
        几页的知识点标成 done，后面的题就再也不会被采集。

        真的没题的页面（翻过了最后一页、或空知识点）永远等不到卡片，超时属正常，
        照样把 HTML 交上去由上层按 site_total 判断。
        """
        try:
            await self.playwright_page.wait_for_selector(
                "div.tk-quest-item", state="attached", timeout=LIST_RENDER_TIMEOUT_MS
            )
        except Exception:
            # 等不到不代表出错，交给上层判断；这里静默是有意的
            pass

    def _remember_position(
        self, page_html: str, url: str, page_no: Optional[int], base_url: str
    ) -> None:
        """记下浏览器现在停在哪一片的第几页，下一次才知道能不能接着点"""
        self._browser_base_url = base_url or self._browser_base_url
        shown = current_page_from_pager(page_html)
        self._browser_page_no = shown if shown is not None else page_no

    async def _try_click_paging(self, target_page: int, base_url: str) -> Optional[str]:
        """
        在分页器里找到指向 target_page 的链接并点它。

        返回渲染后的 HTML；任何一步没把握就返回 None 让调用方退回 goto。
        ★ 点完必须**确认真的到了第 target_page 页**才敢返回 —— 点错一个链接会把
          别的页的题当成第 N 页入库并记进度，是不报错的静默数据损坏。
        """
        page = self.playwright_page
        if page is None or not base_url:
            return None
        if self._browser_base_url != base_url or self._browser_page_no is None:
            # 换了一片，或者还不知道现在停在哪 —— 先 goto 这一片的首页再说
            return None
        if self._browser_page_no == target_page:
            return await page.content()

        try:
            before_html = await page.content()
        except Exception:
            return None
        before_first_id = first_question_id(before_html)

        link = await self._find_pager_link(target_page)
        if link is not None:
            try:
                await link.scroll_into_view_if_needed(timeout=5000)
                # 人不会瞬间点，滚到位到落点之间总有个停顿
                await asyncio.sleep(random.uniform(0.3, 1.2))
                await link.click(timeout=10000)
            except Exception as e:
                utils.logger.warning(f"[ZuJuanClient] 点击第 {target_page} 页失败({e})，退回 goto")
                return None
        elif not await self._jump_via_input(target_page):
            # 页码链接、下一页、跳转框都用不了 —— 只能退回改地址栏
            if not self._pager_dumped:
                self._pager_dumped = True
                utils.logger.warning(
                    f"[ZuJuanClient] 分页器里没有通往第 {target_page} 页的控件，"
                    f"本次及后续均退回直接 goto。分页器实际结构如下：\n"
                    f"{dump_pager_html(before_html)}"
                )
            return None

        page_html = await self._wait_page_changed(before_first_id)
        if page_html is None:
            utils.logger.warning(
                f"[ZuJuanClient] 点了第 {target_page} 页但内容没换，退回 goto"
            )
            return None

        shown = current_page_from_pager(page_html)
        url_ok = re.search(rf"p{target_page}/?$", page.url.rstrip("/") + "/") is not None
        if shown != target_page and not url_ok:
            # 确认不了到底翻到了第几页，绝不能拿这份 HTML 当第 target_page 页用
            utils.logger.warning(
                f"[ZuJuanClient] 点击后无法确认当前页码（分页器读到 {shown}，"
                f"URL {page.url}），退回 goto 保证页码准确"
            )
            return None

        self._browser_base_url = base_url
        self._browser_page_no = target_page
        utils.logger.info(f"[ZuJuanClient] 已通过点击分页器翻到第 {target_page} 页")
        return page_html

    async def _first_visible(self, selectors):
        """按顺序找第一个存在且可见的元素，都没有返回 None"""
        for selector in selectors:
            try:
                locator = self.playwright_page.locator(selector).first
                if await locator.count() and await locator.is_visible():
                    return locator
            except Exception:
                continue
        return None

    async def _find_pager_link(self, target_page: int):
        """
        找分页器里通往目标页的控件。

        真实结构（2026-09 实测）：
            <a data-num="2" data-type="switchPage" data-href="/czsx/zsd4677/o2p2/">2</a>
            <a title="下一页" data-type="nextPage" class="pager-item next-page"></a>  ← 文本是空的
        ★ "下一页"是个图标按钮，:has-text("下一页") 永远匹配不到，只能靠
          data-type / title / class 定位。
        """
        # ① 直接点目标页码。data-num 比 data-href 可靠：页码就在属性里
        link = await self._first_visible((
            f'div.tk-pager a[data-type="switchPage"][data-num="{target_page}"]',
            f'div.tk-pager a[data-type="switchPage"][data-href$="p{target_page}/"]',
            f'a[data-type="switchPage"][data-href*="p{target_page}/"]',
        ))
        if link is not None:
            return link

        # ② 目标正好是下一页时点"下一页"
        if self._browser_page_no is not None and target_page == self._browser_page_no + 1:
            return await self._first_visible((
                'div.tk-pager a[data-type="nextPage"]:not(.disabled)',
                'div.tk-pager a[title="下一页"]:not(.disabled)',
                "div.tk-pager a.next-page:not(.disabled)",
            ))
        return None

    async def _jump_via_input(self, target_page: int) -> bool:
        """
        用分页器自带的"跳转"输入框翻到任意页。

        ★ 这是能到达远处页码的唯一站内途径：分页器 data-cap="10"，一次只显示
          10 个页码，要到第 387 页要么点 386 次下一页，要么用这个框。
            <input id="iptGotoNum" class="go-to__page" value="1">
            <a data-type="confirmGoto" onclick="tkBusiness.pageGo.GoSpecifyNew()">确定</a>
        """
        box = await self._first_visible((
            "div.tk-pager input#iptGotoNum",
            "div.tk-pager input.go-to__page",
        ))
        button = await self._first_visible((
            'div.tk-pager a[data-type="confirmGoto"]',
            "div.tk-pager .go-to a.confirm-btn",
        ))
        if box is None or button is None:
            return False
        try:
            await box.scroll_into_view_if_needed(timeout=5000)
            await box.fill(str(target_page))
            await asyncio.sleep(random.uniform(0.2, 0.8))
            await button.click(timeout=10000)
            return True
        except Exception as e:  # noqa: BLE001 - 跳转框用不了就退回 goto
            utils.logger.warning(f"[ZuJuanClient] 分页器跳转框失败({e})")
            return False

    async def _wait_page_changed(self, before_first_id: Optional[str]) -> Optional[str]:
        """
        轮询等第一张卡片换掉。

        翻页链接是 data-type="switchPage" 的 JS 链接，可能走 AJAX 也可能整页跳转，
        wait_for_load_state 未必会触发，所以直接盯内容。
        """
        deadline = time.monotonic() + CLICK_PAGING_TIMEOUT_SEC
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            try:
                page_html = await self.playwright_page.content()
            except Exception:
                # 正在跳转时取不到内容属正常
                continue
            if page_status(page_html) is not PageStatus.OK:
                # 翻页翻出个挑战页/验证页，交给上层按风控层级处置
                return page_html
            new_first = first_question_id(page_html)
            # ★ 必须等到新的一页真的有卡片，不能只看"和上一页不一样"：AJAX 换页
            #   时列表会先被清空再填回来，那一瞬间 first_question_id 是 None，
            #   None != 上一页的 ID 也算"换掉了"，于是把一个零卡片的中间态当成
            #   目标页返回 —— 上层看到"这一页没题"就会把知识点标成 done。
            #   目标页本来就没题（翻过了最后一页）时这里会一直等到超时返回 None，
            #   调用方退回 goto，由上层按 site_total 判断，不会漏判
            if new_first is not None and new_first != before_first_id:
                return page_html
        return None

    async def wait_human_solve(self, url: str) -> str:
        """
        检测到人机验证时把页面推到人眼前，等人拖完滑块。

        对这个场景人工介入的性价比远高于自动破解：过完一次拿到的新凭证同样可以
        交给 httpx 继续高速翻页，成本被摊薄；而 WAF 验证码是会 A/B 换形态的第三方
        组件，自动解是一场没有尽头的对抗。
        """
        if not getattr(config, "ZUJUAN_ENABLE_HUMAN_SOLVE", True):
            raise DataFetchError(
                f"[ZuJuanClient.wait_human_solve] 检测到人机验证，但 ZUJUAN_ENABLE_HUMAN_SOLVE "
                f"为 False，已放弃: {url}"
            )

        headless = config.CDP_HEADLESS if config.ENABLE_CDP_MODE else config.HEADLESS
        if headless:
            raise DataFetchError(
                "[ZuJuanClient.wait_human_solve] 检测到人机验证，但浏览器运行在无头模式下，"
                "人工无法操作。请把 CDP_HEADLESS / HEADLESS 设为 False 后重试"
            )

        timeout = int(getattr(config, "ZUJUAN_HUMAN_SOLVE_TIMEOUT", 180))
        try:
            await self.playwright_page.bring_to_front()
        except Exception as e:  # 某些 CDP 场景下不支持置顶，不影响人工操作
            utils.logger.debug(f"[ZuJuanClient.wait_human_solve] bring_to_front failed: {e}")

        utils.logger.warning(
            f"⚠️  [ZuJuanClient] 检测到人机验证，请在浏览器窗口中手动完成验证"
            f"（最多等待 {timeout} 秒）: {url}"
        )

        for elapsed in range(timeout):
            await asyncio.sleep(1)
            try:
                page_html = await self.playwright_page.content()
            except Exception:
                # 人过验证时页面正在跳转，取不到内容属正常，下一秒再看
                continue
            if page_status(page_html) not in (PageStatus.CAPTCHA, PageStatus.JS_CHALLENGE):
                utils.logger.info(
                    f"[ZuJuanClient.wait_human_solve] ✅ 人机验证已通过（耗时 {elapsed + 1}s）"
                )
                # ★ 人刚过完验证，WAF 对这个 IP 正处在高度戒备。这时候立刻用 httpx
                #   打过去（TLS 指纹和 Chrome 不同）极容易再次触发，就会变成"每翻
                #   一页弹一次滑块"。先让浏览器顶一段时间，让这张凭证稳下来
                self._enter_browser_cooldown("人机验证刚通过")
                # 过验证过程中页面跳转过，浏览器停在哪已经不可信了
                self._browser_base_url = None
                self._browser_page_no = None
                return page_html

        raise DataFetchError(f"[ZuJuanClient.wait_human_solve] 人机验证等待超时（{timeout}s）: {url}")

    async def _sync_cookies_from_page(self) -> None:
        """把当前浏览器页面上下文里的 Cookie 同步到 httpx"""
        if not self.playwright_page:
            return
        try:
            await self.update_cookies(self.playwright_page.context)
        except Exception as e:
            utils.logger.warning(f"[ZuJuanClient._sync_cookies_from_page] sync cookies failed: {e}")

    async def pong(self) -> bool:
        """组卷网列表页无需登录，这里只探测有没有被 WAF 挡在门外"""
        try:
            page_html = await self.get_page_html(self._host)
            return page_status(page_html) is not PageStatus.CAPTCHA
        except Exception as e:
            utils.logger.error(f"[ZuJuanClient.pong] failed: {e}")
            return False
