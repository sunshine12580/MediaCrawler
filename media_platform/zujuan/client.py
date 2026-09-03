# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zujuan/client.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

import asyncio
import random
from typing import Optional

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
from .help import ZUJUAN_HOST, PageStatus, page_status

# 被限流时的退避次数，参照 kuaishou 的做法用指数退避 + 抖动
MAX_RATE_LIMIT_RETRY = 3


class ZuJuanClient(AbstractApiClient, ProxyRefreshMixin):
    """
    组卷网页面客户端。

    组卷网在 CDN 层挂了 JS 挑战（阿里云 WAF），直接用 httpx 请求只会拿到一段
    挑战脚本。所以流程是：先用浏览器打开一次首页让挑战自行通过，把浏览器的
    Cookie 拿过来交给 httpx 翻页；万一 httpx 仍然被挑战拦下，就退回浏览器取页面。

    阿里云 WAF 是阶梯式升级的，这里按 :class:`PageStatus` 分级处置：

    - ``JS_CHALLENGE`` —— 退回浏览器自动过，过完把新 Cookie 同步回 httpx
    - ``CAPTCHA``（滑块/点选）—— 停下来把页面推到人眼前，等人过完再继续
    - ``429`` 限流 —— 指数退避重试
    - ``UNKNOWN`` —— 认不出来一律当失败，绝不静默写入空数据
    """

    def __init__(
        self,
        timeout: int = 30,
        user_agent: Optional[str] = None,
        cookie_str: str = "",
        proxy: Optional[str] = None,
        playwright_page: Optional[Page] = None,
    ):
        self.timeout = timeout
        self.proxy = proxy
        self.playwright_page = playwright_page
        self._host = ZUJUAN_HOST
        self.headers = {
            "User-Agent": user_agent or utils.get_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cookie": cookie_str,
            "Referer": self._host,
        }

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
        async with make_async_client(proxy=self.proxy, follow_redirects=True) as client:
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

    async def get_page_html(self, url: str, referer: str = "") -> str:
        """
        取一个页面的 HTML：优先 httpx（快），拿不到目标数据时按风控层级分级处置。
        """
        headers = dict(self.headers)
        if referer:
            headers["Referer"] = referer

        for attempt in range(MAX_RATE_LIMIT_RETRY):
            try:
                return await self.request("GET", url, headers=headers)
            except RateLimitError as e:
                if attempt >= MAX_RATE_LIMIT_RETRY - 1:
                    utils.logger.warning(
                        f"[ZuJuanClient.get_page_html] still rate limited after "
                        f"{MAX_RATE_LIMIT_RETRY} attempts ({e}), fallback to browser: {url}"
                    )
                    break
                delay = 5 * (2**attempt) + random.uniform(0, 2)
                utils.logger.warning(
                    f"[ZuJuanClient.get_page_html] rate limited on {url}, retry in {delay:.1f}s, "
                    f"attempt {attempt + 1}/{MAX_RATE_LIMIT_RETRY}"
                )
                await asyncio.sleep(delay)
            except CaptchaPageError:
                utils.logger.warning(
                    f"[ZuJuanClient.get_page_html] httpx hit WAF captcha, hand over to browser: {url}"
                )
                break
            except ChallengePageError:
                utils.logger.warning(
                    f"[ZuJuanClient.get_page_html] httpx got no question data, fallback to browser: {url}"
                )
                break
            except Exception as e:
                utils.logger.warning(
                    f"[ZuJuanClient.get_page_html] httpx request failed ({e}), fallback to browser: {url}"
                )
                break

        return await self.fetch_html_by_browser(url)

    async def fetch_html_by_browser(self, url: str) -> str:
        """
        用浏览器打开页面并返回渲染后的 HTML。

        浏览器这一趟的结果是权威的：它带着真实指纹和完整会话，如果它都没看到题目
        又没有任何拦截特征，那就是这一页本来就没题（比如翻过了最后一页），交给上层
        自然停止；只有确实被拦截时才报错或转人工。
        """
        if not self.playwright_page:
            raise DataFetchError("[ZuJuanClient.fetch_html_by_browser] playwright page is not available")

        await self.playwright_page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page_html = await self.playwright_page.content()
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
                    f"[ZuJuanClient.wait_human_solve] ✅ 人机验证已通过（耗时 {elapsed + 1}s），继续抓取"
                )
                return page_html

        raise DataFetchError(f"[ZuJuanClient.wait_human_solve] 人机验证等待超时（{timeout}s）: {url}")

    async def _sync_cookies_from_page(self) -> None:
        """把当前浏览器页面上下文里的 Cookie 同步到 httpx 请求头"""
        if not self.playwright_page:
            return
        try:
            await self.update_cookies(self.playwright_page.context)
        except Exception as e:
            utils.logger.warning(f"[ZuJuanClient._sync_cookies_from_page] sync cookies failed: {e}")

    async def update_cookies(self, browser_context: BrowserContext):
        """把浏览器里的 Cookie（含过挑战后的凭证）同步到 httpx 请求头"""
        cookie_str, cookie_dict = utils.convert_cookies(await browser_context.cookies())
        self.headers["Cookie"] = cookie_str
        return cookie_str, cookie_dict

    async def pong(self) -> bool:
        """组卷网列表页无需登录，这里只探测有没有被 WAF 挡在门外"""
        try:
            page_html = await self.get_page_html(self._host)
            return page_status(page_html) is not PageStatus.CAPTCHA
        except Exception as e:
            utils.logger.error(f"[ZuJuanClient.pong] failed: {e}")
            return False
