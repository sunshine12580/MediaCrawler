# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zujuan/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

import asyncio
import os
import random
from typing import Dict, List, Optional

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)

import config
from base.base_crawler import AbstractCrawler
from model.m_zujuan import ZujuanQuestion
from proxy.proxy_ip_pool import IpInfoModel, ProxyIpPool, create_ip_pool
from store import zujuan as zujuan_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from .client import ZuJuanClient
from .help import ZUJUAN_HOST, ZuJuanExtractor, build_page_url


class ZuJuanCrawler(AbstractCrawler):
    context_page: Page
    zujuan_client: ZuJuanClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self) -> None:
        self.index_url = ZUJUAN_HOST
        self.user_agent = utils.get_user_agent()
        self._extractor = ZuJuanExtractor()
        self.cdp_manager = None
        self.ip_proxy_pool: Optional[ProxyIpPool] = None

    async def start(self) -> None:
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

        async with async_playwright() as playwright:
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[ZuJuanCrawler] Launching browser using CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[ZuJuanCrawler] Launching browser using standard mode")
                self.browser_context = await self.launch_browser(
                    playwright.chromium,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.HEADLESS,
                )
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self.browser_context.new_page()
            # 首页跑一遍 CDN 的 JS 挑战，拿到后续 httpx 请求需要的 Cookie
            await self.context_page.goto(self.index_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            self.zujuan_client = await self.create_zujuan_client(httpx_proxy_format)

            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                await self.search()
            else:
                utils.logger.error(
                    f"[ZuJuanCrawler.start] 组卷网只支持 --type search（按列表页 URL 抓题）,"
                    f" 当前 --type {config.CRAWLER_TYPE} 不支持。"
                    " 题目详情页正文不对未登录用户输出，答案与解析同样需要登录。"
                )

            utils.logger.info("[ZuJuanCrawler.start] Zujuan Crawler finished ...")

    async def search(self) -> None:
        """按配置的列表页 URL 抓题，自动翻页"""
        list_urls: List[str] = [url.strip() for url in config.ZUJUAN_SPECIFIED_URL_LIST if url.strip()]
        if not list_urls:
            utils.logger.error(
                "[ZuJuanCrawler.search] 没有配置列表页 URL，"
                "请在 config/zujuan_config.py 的 ZUJUAN_SPECIFIED_URL_LIST 中填写，"
                "或用 --specified_id 传入"
            )
            return

        for list_url in list_urls:
            utils.logger.info(f"[ZuJuanCrawler.search] Begin crawl list url: {list_url}")
            source_keyword_var.set(list_url)
            try:
                await self.crawl_list_url(list_url)
            except Exception as e:
                utils.logger.error(f"[ZuJuanCrawler.search] Crawl list url {list_url} failed: {e}")

    async def crawl_list_url(self, list_url: str) -> None:
        """抓取单个列表页 URL 下的所有题目，直到翻完或达到 CRAWLER_MAX_NOTES_COUNT"""
        start_page = max(1, config.START_PAGE)
        max_question_count = config.CRAWLER_MAX_NOTES_COUNT
        max_page_count = getattr(config, "ZUJUAN_MAX_PAGE_PER_URL", 0)

        page = start_page
        saved_count = 0
        total_page: Optional[int] = None
        page_url_template: Optional[str] = None

        while True:
            page_url = build_page_url(list_url, page, page_url_template)
            utils.logger.info(f"[ZuJuanCrawler.crawl_list_url] Fetching page {page}: {page_url}")
            page_html = await self.zujuan_client.get_page_html(page_url, referer=list_url)

            if page_url_template is None:
                page_url_template = self._extractor.extract_page_url_template(page_html)
            if total_page is None:
                total_page = self._extractor.extract_total_page(page_html)
                total_question = self._extractor.extract_total_question_count(page_html)
                utils.logger.info(
                    f"[ZuJuanCrawler.crawl_list_url] {list_url} 共 {total_question} 题 / {total_page} 页"
                )

            questions: List[ZujuanQuestion] = self._extractor.extract_questions(
                page_html, list_url=list_url, page=page
            )
            if not questions:
                utils.logger.info(f"[ZuJuanCrawler.crawl_list_url] No question on page {page}, stop")
                break

            for question in questions:
                if saved_count >= max_question_count:
                    break
                if not getattr(config, "ZUJUAN_ENABLE_GET_IMAGES", True):
                    question.image_list = ""
                await zujuan_store.update_zujuan_question(question)
                saved_count += 1

            utils.logger.info(
                f"[ZuJuanCrawler.crawl_list_url] Page {page} done, saved {saved_count}/{max_question_count}"
            )

            if saved_count >= max_question_count:
                utils.logger.info("[ZuJuanCrawler.crawl_list_url] Reached CRAWLER_MAX_NOTES_COUNT, stop")
                break
            if total_page and page >= total_page:
                utils.logger.info("[ZuJuanCrawler.crawl_list_url] Reached last page, stop")
                break
            if max_page_count and (page - start_page + 1) >= max_page_count:
                utils.logger.info("[ZuJuanCrawler.crawl_list_url] Reached ZUJUAN_MAX_PAGE_PER_URL, stop")
                break

            page += 1
            # 固定间隔本身也是机器特征，加点抖动，顺便降低被 WAF 升级风控的概率
            sleep_sec = config.CRAWLER_MAX_SLEEP_SEC + random.uniform(1, 3)
            utils.logger.info(
                f"[ZuJuanCrawler.crawl_list_url] Sleeping for {sleep_sec:.1f} seconds before page {page}"
            )
            await asyncio.sleep(sleep_sec)

    async def create_zujuan_client(self, httpx_proxy: Optional[str]) -> ZuJuanClient:
        """用浏览器里已经过完挑战的 Cookie 创建 httpx 客户端"""
        cookie_str, _ = utils.convert_cookies(await self.browser_context.cookies())
        zujuan_client = ZuJuanClient(
            timeout=30,
            user_agent=self.user_agent,
            cookie_str=cookie_str,
            proxy=httpx_proxy,
            playwright_page=self.context_page,
        )
        zujuan_client.init_proxy_pool(self.ip_proxy_pool)
        return zujuan_client

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        utils.logger.info("[ZuJuanCrawler.launch_browser] Begin create browser context ...")
        if config.SAVE_LOGIN_STATE:
            user_data_dir = os.path.join(
                os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM
            )  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent,
            )
            return browser_context

        browser = await chromium.launch(headless=headless, proxy=playwright_proxy)  # type: ignore
        return await browser.new_context(
            viewport={"width": 1920, "height": 1080}, user_agent=user_agent
        )

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        try:
            self.cdp_manager = CDPBrowserManager()
            browser_context = await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )
            browser_info = await self.cdp_manager.get_browser_info()
            utils.logger.info(f"[ZuJuanCrawler] CDP browser info: {browser_info}")
            return browser_context
        except Exception as e:
            utils.logger.error(f"[ZuJuanCrawler] CDP mode launch failed, falling back to standard mode: {e}")
            return await self.launch_browser(playwright.chromium, playwright_proxy, user_agent, headless)

    async def close(self) -> None:
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        elif self.browser_context:
            await self.browser_context.close()
        utils.logger.info("[ZuJuanCrawler.close] Browser context closed ...")
