# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zujuan/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

# ★ 必须放在最前面：本模块和 store.zujuan._progress 互相依赖 —— 爬虫要写进度，
#   而进度层要用 media_platform.zujuan.slicing 的维度定义。谁先被 import 谁就
#   拿到对方的半成品模块。推迟注解求值之后，import 期间不会再去取对方的属性，
#   两种顺序都能起来（tests/test_zujuan_knowledge_crawl.py 里两个方向都锁住了）
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
import random
from typing import Dict, List, Optional, Tuple

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

from store.zujuan import _progress as progress

from . import api as zujuan_api
from . import slicing
from .client import ZuJuanClient, client_hints_from_page_data
from .help import (
    ZUJUAN_HOST,
    PageStatus,
    ZuJuanExtractor,
    build_page_url,
    first_question_id,
    page_status,
)


# 一页明明该有卡片却读回来是空的时，重取几次再判。
# 站点的列表是 domcontentloaded 之后由 JS 填进 DOM 的，网慢时取早了就是一个
# "有 #questioncount、零张卡片"的半成品
EMPTY_PAGE_RETRY = 2

# 每次重取之间的等待区间（秒），随机取 —— 固定间隔本身就是机器特征
EMPTY_PAGE_RETRY_SLEEP = (3.0, 6.0)


@dataclass
class WatchTarget:
    """人工翻页模式的一个待采项：一个知识点，或它底下的一片。

    parts 为空就是"不带筛选条件的整个知识点"；题量超过翻页硬顶时会被就地展开成
    若干带筛选条件的子片，人只需要跟着脚本给的地址一片片翻。
    """

    knowledge_id: str
    parts: Dict[str, str]
    title: Optional[str] = None

    @property
    def slice_key(self) -> str:
        return slicing.slice_key(self.parts)

    @property
    def label(self) -> str:
        name = f"{self.knowledge_id}「{self.title}」" if self.title else self.knowledge_id
        return f"{name}·{slicing.slice_name(self.parts)}" if self.parts else name


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
        # 本次运行累计入库的题数，用来卡 ZUJUAN_MAX_QUESTIONS_PER_RUN
        self._saved_count = 0
        # 人工翻页模式下按知识点缓存进度对象，避免每页都去查两次库
        self._watch_progress_cache: Dict[str, tuple] = {}
        # 人工翻页模式的待采队列，以及用来跳转的标签页
        self._watch_queue: List[WatchTarget] = []
        self._watch_nav_page = None
        # api 模式：每片首页由浏览器取到的权威结果 {slice_key: (页码, 题目ID列表, 题数)}，
        # 以及已经通过对齐校验的片。校验一旦失败就整轮关掉接口退回浏览器
        self._api_probe: Dict[str, Tuple[int, List[str], Optional[int]]] = {}
        self._api_verified: set = set()
        self._api_enabled = True

    @staticmethod
    def _check_api_config() -> None:
        """api 模式的参数体检，不合法直接报错而不是跑到一半写坏数据"""
        page_size = int(getattr(config, "ZUJUAN_API_PAGE_SIZE", 0) or 0)
        if page_size and page_size != slicing.PAGE_SIZE:
            raise ValueError(
                f"[ZuJuanCrawler] ZUJUAN_API_PAGE_SIZE={page_size} 不被支持。"
                f"covered_pages 里几十万条进度都是按 {slicing.PAGE_SIZE} 条一页记的，"
                f"页大小一变这些页码就全失去意义（{page_size} 条一页的第 5 页和 "
                f"{slicing.PAGE_SIZE} 条一页的第 5 页不是同一批题），断点续采会静默跳页。"
                f"换页大小是一次独立的数据迁移，不能只改这个开关"
            )
        page_base = int(getattr(config, "ZUJUAN_API_PAGE_BASE", 1) or 0)
        if page_base not in (0, 1):
            raise ValueError(
                f"[ZuJuanCrawler] ZUJUAN_API_PAGE_BASE 只能是 0 或 1，当前是 {page_base}"
            )

    async def start(self) -> None:
        if self._api_mode():
            self._check_api_config()
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

            crawler_type_var.set(config.CRAWLER_TYPE)

            if getattr(config, "ZUJUAN_CRAWL_MODE", "knowledge") == "watch":
                # ★ 人工翻页模式在这里就分流：不开新标签页、不 goto、不建 httpx 客户端。
                #   浏览器完全由人操作，脚本一个导航动作都不做
                await self.watch_manual_browsing()
                utils.logger.info("[ZuJuanCrawler.start] Zujuan Crawler finished ...")
                return

            self.context_page = await self.browser_context.new_page()
            # 首页跑一遍 CDN 的 JS 挑战，拿到后续 httpx 请求需要的 Cookie
            await self.context_page.goto(self.index_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            self.zujuan_client = await self.create_zujuan_client(httpx_proxy_format)

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
        """--type search 的入口，按 ZUJUAN_CRAWL_MODE 分流到两种抓法"""
        mode = getattr(config, "ZUJUAN_CRAWL_MODE", "knowledge")
        if mode == "knowledge":
            await self.crawl_by_knowledge()
        elif mode == "url":
            await self.crawl_by_url()
        elif mode == "watch":
            await self.watch_manual_browsing()
        else:
            utils.logger.error(
                f"[ZuJuanCrawler.search] 不认识的 ZUJUAN_CRAWL_MODE: {mode}，"
                f"可选 knowledge（按知识点树遍历）/ url（按写死的列表页 URL）/ watch（人工翻页，脚本只入库）"
            )

    # ------------------------------------------------------------------
    # 抓法一：按知识点树遍历（见 docs/zujuan/知识点切片抓取规范.md）
    # ------------------------------------------------------------------

    @property
    def url_prefix(self) -> str:
        """列表页 URL 里的学段前缀，czsx=初中 / gzsx=高中"""
        return getattr(config, "ZUJUAN_URL_PREFIX", "czsx") or "czsx"

    async def crawl_by_knowledge(self) -> None:
        """遍历 knowledge_tree 里待抓的叶子知识点"""
        knowledge_ids = [
            item.strip()
            for item in getattr(config, "ZUJUAN_KNOWLEDGE_ID_LIST", []) or []
            if item and item.strip()
        ]
        targets = await progress.fetch_leaf_targets(
            limit=int(getattr(config, "ZUJUAN_KNOWLEDGE_LIMIT", 0) or 0),
            knowledge_ids=knowledge_ids or None,
            bank_id=(getattr(config, "ZUJUAN_BANK_ID", "") or None),
            only_uncrawled=bool(getattr(config, "ZUJUAN_ONLY_UNCRAWLED", False)),
            exclude_path_keywords=getattr(config, "ZUJUAN_EXCLUDE_PATHS", None),
        )
        if not targets:
            utils.logger.info(
                "[ZuJuanCrawler.crawl_by_knowledge] 没有待抓的知识点 —— knowledge_tree 里"
                " child_count=0 且 scrape_status 属于 none/partial/slicing 的行是空的"
            )
            return

        max_pages = self._max_pages_per_knowledge()
        scope = f"本次待抓 {len(targets)} 个叶子知识点"
        if max_pages:
            scope += f"，浅采模式：每个最多翻 {max_pages} 页，不做超量切片"
        utils.logger.info(f"[ZuJuanCrawler.crawl_by_knowledge] {scope}")
        for index, target in enumerate(targets, start=1):
            if self._budget_exhausted():
                utils.logger.info(
                    "[ZuJuanCrawler.crawl_by_knowledge] 达到 ZUJUAN_MAX_QUESTIONS_PER_RUN，停止"
                )
                break

            utils.logger.info(
                f"[ZuJuanCrawler.crawl_by_knowledge] ({index}/{len(targets)}) "
                f"{target.knowledge_id}「{target.title}」status={target.scrape_status} "
                f"last_page={target.last_page} covered={target.covered_pages or '-'}"
            )
            source_keyword_var.set(target.knowledge_id)
            try:
                await self.crawl_knowledge_point(target)
            except Exception as e:  # noqa: BLE001 - 一个知识点失败不能拖垮整轮
                utils.logger.error(
                    f"[ZuJuanCrawler.crawl_by_knowledge] {target.knowledge_id} 抓取失败: {e}"
                )
                continue

            if index < len(targets):
                await self._sleep_between(
                    getattr(config, "ZUJUAN_KNOWLEDGE_SLEEP_RANGE", (5.0, 12.0)),
                    "下一个知识点",
                )

    async def crawl_knowledge_point(self, target: progress.KnowledgeTarget) -> str:
        """抓一个叶子知识点：能翻完就翻完，翻不完就切片"""
        slices = await progress.fetch_slice_map(target.knowledge_id)
        status = await self._crawl_slice(target, {}, slices)
        # ★ collected 必须重算，不能每采一道 +1 —— 采集可以重跑，累加会一直膨胀
        collected = await progress.refresh_collected(target.knowledge_id)
        utils.logger.info(
            f"[ZuJuanCrawler.crawl_knowledge_point] {target.knowledge_id}"
            f"「{target.title}」结束，状态 {status}，站点 {target.site_total} 道 / 库里 {collected} 道"
        )
        return status

    async def _crawl_slice(
        self,
        target: progress.KnowledgeTarget,
        parts: Dict[str, str],
        slices: Dict[str, progress.SliceProgress],
    ) -> str:
        """处理一片（parts 为空就是不带筛选条件的整个知识点），必要时递归往下切"""
        key = slicing.slice_key(parts)
        label = target.knowledge_id + (f"/{key}" if key else "")
        is_root = not parts

        force = bool(getattr(config, "ZUJUAN_FORCE_RECRAWL", False))
        if is_root:
            status, resume_page, known_total = (
                target.scrape_status,
                target.resume_page,
                target.site_total,
            )
        else:
            row = slices.get(key)
            status = row.scrape_status if row else progress.STATUS_NONE
            resume_page = row.resume_page if row else 1
            known_total = row.site_total if row else None

        if force:
            # 重跑就是从第 1 页重来，不看已有进度（单题层面还有 stem_hash 判重兜底）
            resume_page = 1
        elif status in progress.TERMINAL_STATUS:
            utils.logger.info(
                f"[ZuJuanCrawler] {label} 状态已是 {status}，跳过"
                f"（要重跑把 ZUJUAN_FORCE_RECRAWL 打开）"
            )
            return status

        if status == progress.STATUS_SLICING and not force:
            if self._sweep_mode():
                # 已经在切片采了的知识点，手里的题远不止浅采这几页，跳过
                utils.logger.info(f"[ZuJuanCrawler] {label} 已在切片采集中，浅采跳过")
                return status
            # 上次已经决定切片了，直接往下钻，不用再读一次首页
            return await self._descend(target, parts, slices, known_total)

        outcome, site_total = await self._page_through(target, parts, slices, resume_page)
        if outcome is slicing.SliceOutcome.NEED_SLICE:
            if self._sweep_mode():
                # 浅采不下钻。翻页过程中才发现超硬顶（站点新增题、或撞上 999 页
                # 重复返回）也一样：记成 partial，等以后深采时再切
                utils.logger.info(
                    f"[ZuJuanCrawler] {label} 需要切片，浅采模式不下钻，"
                    f"记为 partial 等以后深采"
                )
                outcome = slicing.SliceOutcome.INTERRUPTED
            else:
                return await self._descend(target, parts, slices, site_total)

        await self._write_progress(
            target, parts, slices, scrape_status=outcome.value, site_total=site_total
        )
        if outcome is slicing.SliceOutcome.DONE and not is_root:
            await progress.refresh_slice_collected(target.knowledge_id, key)
        return outcome.value

    async def _page_through(
        self,
        target: progress.KnowledgeTarget,
        parts: Dict[str, str],
        slices: Dict[str, progress.SliceProgress],
        start_page: int,
    ) -> Tuple["slicing.SliceOutcome", Optional[int]]:
        """顺序翻页，带翻页硬顶检测。返回 (结果, 站点报的题数)"""
        key = slicing.slice_key(parts)
        label = target.knowledge_id + (f"/{key}" if key else "")
        base_url = slicing.build_list_url(target.knowledge_id, parts, prefix=self.url_prefix)

        first_page = max(1, start_page)
        max_pages = self._max_pages_per_knowledge()
        page = first_page
        prev_ids: Optional[List[str]] = None
        site_total: Optional[int] = None
        page_url_template: Optional[str] = None

        while True:
            if self._budget_exhausted():
                utils.logger.info(f"[ZuJuanCrawler] {label} 达到本次入库预算，保留未完成状态")
                return slicing.SliceOutcome.INTERRUPTED, site_total

            page_url = build_page_url(base_url, page, page_url_template)
            utils.logger.info(f"[ZuJuanCrawler] {label} 第 {page} 页: {page_url}")
            page_html, total = await self._fetch_list_page(
                target, parts, page, first_page, page_url, base_url
            )
            if page_url_template is None:
                page_url_template = self._extractor.extract_page_url_template(page_html)
            if total is None:
                # ★ 连"共计 N 道试题"都读不到 —— 正常列表页哪怕这一页没卡片这个数
                #   也该在，读不到说明打开的多半不是列表页（被拦截/结构变了）。
                #   原样保留"还没翻完"，下次从这一页重试；误判成"翻完了"的代价是
                #   这个知识点后面的题永远不会再被采集
                utils.logger.warning(
                    f"[ZuJuanCrawler] {label} 第 {page} 页读不到「共计 N 道试题」，"
                    f"保留未完成状态下次重试: {page_url}"
                )
                return slicing.SliceOutcome.INTERRUPTED, site_total
            site_total = total

            if total == 0:
                utils.logger.info(f"[ZuJuanCrawler] {label} 站点说这里没题")
                return slicing.SliceOutcome.EMPTY, 0

            if page == first_page and slicing.exceeds_hard_cap(total):
                if max_pages:
                    # 浅采只铺底，不在这里炸出一堆分片 —— 记下站点总数，照样翻够
                    # N 页就走，状态留 partial，等以后深采时再按维度切
                    utils.logger.info(
                        f"[ZuJuanCrawler] {label} 共 {total} 道，超过翻页硬顶 "
                        f"{slicing.HARD_CAP}；浅采模式不切片，先翻 {max_pages} 页铺底"
                    )
                else:
                    # 读到这个数字的第一时间就决定改走切片，不用傻等真的翻到第 999 页
                    utils.logger.info(
                        f"[ZuJuanCrawler] {label} 共 {total} 道，超过翻页硬顶 "
                        f"{slicing.HARD_CAP}，转切片"
                    )
                    return slicing.SliceOutcome.NEED_SLICE, total

            questions: List[ZujuanQuestion] = self._extractor.extract_questions(
                page_html, list_url=page_url, page=page
            )
            if not questions and page < slicing.total_pages(total):
                # ★ 站点说共 N 页，这一页却一张卡片都没有 —— 两个数据自相矛盾，
                #   多半是页面还没渲染完就被读走了。重取几次给它时间
                total, questions = await self._refetch_empty_page(
                    label, page_url, base_url, page, total
                )
                site_total = total
                if total == 0:
                    utils.logger.info(f"[ZuJuanCrawler] {label} 站点说这里没题")
                    return slicing.SliceOutcome.EMPTY, 0

            if not questions:
                if page < slicing.total_pages(total):
                    # ★ 重取完还是空，但站点明说后面还有页 —— 保留"还没翻完"下次重试。
                    #   这里绝不能返回 DONE：只翻到第 page 页却记成"采完了"，这个知识点
                    #   后面的题就再也不会被采集，而且不报错（和 site_total 误判成 0 是
                    #   同一类静默数据损坏）。线上 zsd6026 就是这么在 site_total=656
                    #   （66 页）的情况下停在第 8 页被标成 done 的
                    utils.logger.warning(
                        f"[ZuJuanCrawler] {label} 第 {page} 页重取 {EMPTY_PAGE_RETRY} 次"
                        f"仍没有题目卡片，但站点说共 {slicing.total_pages(total)} 页"
                        f"（{total} 道）—— 保留未完成状态下次重试: {page_url}"
                    )
                    return slicing.SliceOutcome.INTERRUPTED, total
                if slicing.exceeds_hard_cap(total):
                    # ★ total_pages() 封顶在 999，所以超硬顶的片"翻到最后一页"其实是
                    #   翻到了硬顶，后面还有题拿不到 —— 必须转切片而不是标 done。
                    #   线上有 3 条 last_page=999 的分片就是这么被标成 done 的
                    utils.logger.warning(
                        f"[ZuJuanCrawler] {label} 翻到第 {page} 页没有题目卡片，"
                        f"但站点报 {total} 道超过硬顶 {slicing.HARD_CAP}，转切片"
                    )
                    return slicing.SliceOutcome.NEED_SLICE, total
                # 站点报的页数也到头了，这才是正常翻到底，和撞硬顶是两回事
                utils.logger.info(f"[ZuJuanCrawler] {label} 第 {page} 页没有题目卡片，翻到底了")
                return slicing.SliceOutcome.DONE, total

            page_ids = [question.question_id for question in questions]
            if prev_ids is not None and page_ids == prev_ids:
                # ★ 撞上 999 页硬顶：站点不报错也不返回空页，而是把上一页原样又给一遍。
                #   不检测的话循环会一直跑，反复处理同样 10 道题
                utils.logger.warning(
                    f"[ZuJuanCrawler] {label} 第 {page} 页与上一页题目完全相同，"
                    f"撞上翻页硬顶，停止翻页转切片"
                )
                return slicing.SliceOutcome.NEED_SLICE, total

            await self._save_questions(questions, label, page)
            await self._write_page_progress(target, parts, slices, page, total)
            prev_ids = page_ids

            last_page = slicing.total_pages(total)
            if page >= last_page:
                if slicing.exceeds_hard_cap(total):
                    # 翻的过程中站点又加题、加过了硬顶
                    utils.logger.warning(
                        f"[ZuJuanCrawler] {label} 翻到第 {page} 页时站点已涨到 {total} 道，"
                        f"超过硬顶，转切片"
                    )
                    return slicing.SliceOutcome.NEED_SLICE, total
                utils.logger.info(f"[ZuJuanCrawler] {label} 翻完第 {page}/{last_page} 页")
                return slicing.SliceOutcome.DONE, total

            # ★ 页数预算的判断必须放在上面那些"翻到底"的判断**之后**：
            #   站点只有 3 页的知识点要走正常的 DONE，不能因为预算是 5 页就被
            #   记成 partial 而永远采不完。反过来，这里也绝不能返回 DONE ——
            #   只翻了 N 页却标成"采完了"，这个知识点后面的题就再也不会被采集，
            #   而且不报错（和 site_total 误判成 0 是同一类静默数据损坏）
            if max_pages and page - first_page + 1 >= max_pages:
                utils.logger.info(
                    f"[ZuJuanCrawler] {label} 浅采到第 {page} 页"
                    f"（共 {last_page} 页，本轮预算 {max_pages} 页），保留未完成状态"
                )
                return slicing.SliceOutcome.INTERRUPTED, total

            page += 1
            await self._sleep_between(
                getattr(config, "ZUJUAN_PAGE_SLEEP_RANGE", (2.0, 5.0)),
                f"{label} 第 {page} 页",
            )

    async def _fetch_list_page(
        self,
        target: progress.KnowledgeTarget,
        parts: Dict[str, str],
        page: int,
        first_page: int,
        page_url: str,
        base_url: str,
    ) -> Tuple[str, Optional[int]]:
        """取一页列表，返回 (卡片 HTML, 站点报的题数)。题数没读到一律返回 None。

        api 模式下每一片的**首页仍然走浏览器** —— 那一趟本来就要做：过 WAF 挑战、
        刷新 Cookie、读防伪令牌、读"共计 N 道试题"。之后的页才走接口。一片动辄
        几百页，摊到每页的浏览器开销可以忽略，却把风控处置那一整套原样保留了下来。
        """
        key = slicing.slice_key(parts)
        label = target.knowledge_id + (f"/{key}" if key else "")

        if self._api_mode() and self._api_enabled and page > first_page:
            if await self._api_aligned(target, parts, key, label, base_url):
                result = await self.zujuan_client.fetch_list_api(
                    target.knowledge_id,
                    parts,
                    page,
                    referer=page_url,
                    bank_id=str(getattr(config, "ZUJUAN_BANK_ID", "2") or "2"),
                )
                if result is not None:
                    return result.html, result.total
                # 接口这一趟没给出能认的结果 —— 退回浏览器把这一页重新取一遍，
                # 绝不拿"没读到"当"这一页没题"
                utils.logger.info(f"[ZuJuanCrawler] {label} 第 {page} 页改用浏览器重取")

        page_html = await self.zujuan_client.get_page_html(
            page_url, referer=base_url, page_no=page, base_url=base_url
        )
        total = self._extractor.extract_site_total(page_html)
        if self._api_mode() and page == first_page:
            # 记下这一页的权威结果，等第一次要用接口时拿它做对齐校验
            self._api_probe[key] = (page, self._page_ids(page_html), total)
        return page_html, total

    @staticmethod
    def _api_mode() -> bool:
        return str(getattr(config, "ZUJUAN_FETCH_MODE", "hybrid") or "").lower() == "api"

    @staticmethod
    def _page_ids(page_html: str) -> List[str]:
        return zujuan_api.question_ids(page_html)

    async def _api_aligned(
        self,
        target: progress.KnowledgeTarget,
        parts: Dict[str, str],
        key: str,
        label: str,
        base_url: str,
    ) -> bool:
        """这一片第一次用接口之前，先确认接口和浏览器看到的是同一页。

        ★ 这道校验是整个 api 模式能不能用的前提。页码基数（curPage 从 0 还是 1 数）
          和筛选参数映射（quesType/quesDiff/quesYear 对应哪个码）猜错了都**不会报错**：
          前者让每一页整体错位一页，后者让筛选条件被忽略、把整个知识点的题当成某个
          分片入库。两种都是采得好好的、进度也照记，只有数据是错的。

        校验方式是拿浏览器刚取到的那一页，用同一个页码再走一次接口，比题目 ID 列表
        和题数。对不上就整轮关掉 api 模式退回浏览器 —— 慢，但不会写坏数据。
        """
        if key in self._api_verified:
            return True
        if not bool(getattr(config, "ZUJUAN_API_VERIFY_FIRST_PAGE", True)):
            self._api_verified.add(key)
            return True

        probe = self._api_probe.get(key)
        if probe is None:
            # 没有可比的权威页（比如首页也是接口取的），不敢用
            return False
        probe_page, browser_ids, browser_total = probe
        if not browser_ids:
            # 浏览器那一页本身就没卡片，比不出什么，等下一片再校验
            return False

        result = await self.zujuan_client.fetch_list_api(
            target.knowledge_id,
            parts,
            probe_page,
            referer=base_url,
            bank_id=str(getattr(config, "ZUJUAN_BANK_ID", "2") or "2"),
        )
        if result is None:
            utils.logger.warning(f"[ZuJuanCrawler] {label} 接口对齐校验没拿到结果，本片继续走浏览器")
            return False

        api_ids = self._page_ids(result.html)
        if api_ids == browser_ids and (browser_total is None or result.total == browser_total):
            self._api_verified.add(key)
            utils.logger.info(
                f"[ZuJuanCrawler] {label} 接口对齐校验通过"
                f"（第 {probe_page} 页 {len(api_ids)} 道，共 {result.total} 道），后续走接口"
            )
            return True

        self._api_enabled = False
        utils.logger.error(
            f"[ZuJuanCrawler] ✗ {label} 接口对齐校验失败，本轮改回浏览器翻页。"
            f"第 {probe_page} 页：浏览器 {len(browser_ids)} 道 / 接口 {len(api_ids)} 道，"
            f"题数 浏览器 {browser_total} / 接口 {result.total}。"
            f"浏览器前三个 ID {browser_ids[:3]}，接口前三个 {api_ids[:3]}。"
            f"多半是 ZUJUAN_API_PAGE_BASE 填错（页码整体错位），"
            f"或筛选参数映射不对（接口题数等于整个知识点的题数就是这种）"
        )
        return False

    async def _refetch_empty_page(
        self,
        label: str,
        page_url: str,
        base_url: str,
        page: int,
        total: int,
    ) -> Tuple[int, List[ZujuanQuestion]]:
        """一页该有卡片却读回来是空的，重取几次。返回 (站点报的题数, 题目列表)。

        读不到新的"共计 N 道"就沿用旧的 —— None 是"这一趟没读到"，不能拿它冲掉
        上一次读到的真实值，否则页数算不出来又会退回"翻到底了"的误判。
        """
        # ★ 重取一律走 get_page_html（api 模式下就是浏览器）而不是接口：
        #   浏览器那一趟的结果是权威的 —— 它带着真实指纹和完整会话，它都没看到题
        #   又没有拦截特征，才敢说这一页真的没题
        questions: List[ZujuanQuestion] = []
        for attempt in range(1, EMPTY_PAGE_RETRY + 1):
            utils.logger.warning(
                f"[ZuJuanCrawler] {label} 第 {page} 页没有题目卡片，但站点说共 "
                f"{slicing.total_pages(total)} 页（{total} 道），"
                f"重取第 {attempt}/{EMPTY_PAGE_RETRY} 次"
            )
            await self._sleep_between(EMPTY_PAGE_RETRY_SLEEP, f"{label} 第 {page} 页重取")
            page_html = await self.zujuan_client.get_page_html(
                page_url, referer=base_url, page_no=page, base_url=base_url
            )
            retried_total = self._extractor.extract_site_total(page_html)
            if retried_total is not None:
                total = retried_total
            questions = self._extractor.extract_questions(
                page_html, list_url=page_url, page=page
            )
            if questions:
                utils.logger.info(
                    f"[ZuJuanCrawler] {label} 第 {page} 页重取第 {attempt} 次拿到 "
                    f"{len(questions)} 道，继续翻页"
                )
                break
        return total, questions

    async def _descend(
        self,
        target: progress.KnowledgeTarget,
        parts: Dict[str, str],
        slices: Dict[str, progress.SliceProgress],
        site_total: Optional[int],
    ) -> str:
        """按需下钻一层：题型 -> 难度 -> 解答题子题型 -> 年份"""
        key = slicing.slice_key(parts)
        label = target.knowledge_id + (f"/{key}" if key else "")
        dim = slicing.next_dim(parts)

        if dim is None:
            # 四个维度都用完了还是超硬顶 —— 终止状态，不再自动重试，等人来看
            if site_total is None:
                note = f"切到底仍超硬顶：翻页最多拿到 {slicing.HARD_CAP} 道，站点总数未知"
            else:
                note = (
                    f"切到底仍超硬顶：站点 {site_total} 道，翻页最多拿到 "
                    f"{slicing.HARD_CAP} 道，还差约 {max(0, site_total - slicing.HARD_CAP)} 道"
                )
            utils.logger.error(f"[ZuJuanCrawler] {label} {note}")
            await self._write_progress(
                target,
                parts,
                slices,
                scrape_status=progress.STATUS_CAPPED,
                site_total=site_total,
                note=note[:255],
            )
            return progress.STATUS_CAPPED

        await self._write_progress(
            target, parts, slices, scrape_status=progress.STATUS_SLICING, site_total=site_total
        )

        values = slicing.DIM_VALUES[dim]
        utils.logger.info(
            f"[ZuJuanCrawler] {label} 共 {site_total} 道，按 {dim} 切成 {len(values)} 片"
        )

        child_status: List[str] = []
        for value in values:
            if self._budget_exhausted():
                utils.logger.info(f"[ZuJuanCrawler] {label} 达到本次入库预算，剩下的片下次再切")
                break
            child_parts = dict(parts)
            child_parts[dim] = value.code
            child_status.append(await self._crawl_slice(target, child_parts, slices))

        rolled = self._roll_up(child_status, len(values))
        await self._write_progress(
            target, parts, slices, scrape_status=rolled, site_total=site_total
        )
        utils.logger.info(f"[ZuJuanCrawler] {label} 全部子片处理完，汇总状态 {rolled}")
        return rolled

    @staticmethod
    def _roll_up(child_status: List[str], expected: int) -> str:
        """子片状态汇总到父片。

        只要有一片是 capped，父片也标 capped —— 让人知道这个知识点确实有一部分
        题拿不全，而不是显示"采完了"却比站点少一截。
        """
        if progress.STATUS_CAPPED in child_status:
            return progress.STATUS_CAPPED
        if len(child_status) == expected and all(
            status in (progress.STATUS_DONE, progress.STATUS_EMPTY) for status in child_status
        ):
            return progress.STATUS_DONE
        # 还有片没处理完，保留 slicing，下次直接从没做完的片接着来
        return progress.STATUS_SLICING

    async def _save_questions(
        self, questions: List[ZujuanQuestion], label: str, page: int
    ) -> int:
        """入库一页的题。整页写完才算这一页覆盖到，所以这里不看本次预算"""
        saved = 0
        for question in questions:
            if not question.question_id:
                # 卡片在但抽不到 ID，属于"数量悄悄变少"型故障，必须留痕
                utils.logger.warning(
                    f"[ZuJuanCrawler] {label} 第 {page} 页有一张卡片抽不到 question_id，已跳过"
                )
                continue
            if not question.stem_html:
                # ★抽到了 ID 却没抽到题干，不是"这题没题干"，而是选择器可能失效了
                utils.logger.warning(
                    f"[ZuJuanCrawler] question_id {question.question_id} 抽到了 ID 但题干为空，"
                    f"疑似选择器失效，请检查页面结构"
                )
            await zujuan_store.update_zujuan_question(question)
            self._saved_count += 1
            saved += 1
        return saved

    async def _write_page_progress(
        self,
        target: progress.KnowledgeTarget,
        parts: Dict[str, str],
        slices: Dict[str, progress.SliceProgress],
        page: int,
        site_total: Optional[int],
    ) -> None:
        """★ 每翻完一页立刻写一次进度并提交，中断最多只丢当前正在翻的这一页"""
        if not parts:
            target.covered_pages = slicing.add_page(target.covered_pages, page)
            target.last_page = max(target.last_page or 0, page)
            fields = {
                "last_page": target.last_page,
                "covered_pages": target.covered_pages,
            }
            if site_total is not None:
                fields["site_total"] = site_total
            if target.scrape_status not in progress.TERMINAL_STATUS:
                # ★ 已经 done/capped/empty 的不降级 —— 人工翻页模式下重新浏览一个
                #   采完的知识点，不该把它打回"采了一半"
                fields["scrape_status"] = progress.STATUS_PARTIAL
                target.scrape_status = progress.STATUS_PARTIAL
            await progress.save_tree_progress(target.knowledge_id, **fields)
            return

        key = slicing.slice_key(parts)
        row = slices.get(key)
        if row is None:
            row = progress.SliceProgress(knowledge_id=target.knowledge_id, slice_key=key)
            slices[key] = row
        row.covered_pages = slicing.add_page(row.covered_pages, page)
        row.last_page = max(row.last_page or 0, page)
        fields = {
            "site_total": site_total,
            "last_page": row.last_page,
            "covered_pages": row.covered_pages,
        }
        if row.scrape_status not in progress.TERMINAL_STATUS:
            fields["scrape_status"] = progress.STATUS_PARTIAL
            row.scrape_status = progress.STATUS_PARTIAL
        if site_total is not None:
            row.site_total = site_total
        await self._write_progress(target, parts, slices, **fields)

    async def _write_progress(
        self,
        target: progress.KnowledgeTarget,
        parts: Dict[str, str],
        slices: Dict[str, progress.SliceProgress],
        **fields,
    ) -> None:
        """不带筛选条件写 knowledge_tree，带筛选条件写 knowledge_slice"""
        if fields.get("site_total") is None:
            # 这一趟压根没读到"共计 N 道"（被拦截之类），别拿 NULL 把上次读到的数冲掉
            fields.pop("site_total", None)
        if not parts:
            await progress.save_tree_progress(target.knowledge_id, **fields)
            if "scrape_status" in fields:
                target.scrape_status = fields["scrape_status"]
            if fields.get("site_total") is not None:
                target.site_total = fields["site_total"]
            return

        key = slicing.slice_key(parts)
        dim = slicing.current_dim(parts)
        payload = dict(fields)
        payload.setdefault("dim", dim)
        payload.setdefault("slice_name", slicing.slice_name(parts))
        # ★ depth 存的是维度在级联里的序号（qtype=1 difficulty=2 sub_type=3 year=4），
        #   不是"实际切了几层" —— 单选题跳过了子题型，它底下的年份片 depth 仍是 4。
        #   线上历史数据就是这个口径
        payload.setdefault("depth", slicing.dim_depth(dim))
        await progress.save_slice_progress(target.knowledge_id, key, **payload)

        row = slices.get(key)
        if row is None:
            row = progress.SliceProgress(knowledge_id=target.knowledge_id, slice_key=key)
            slices[key] = row
        if "scrape_status" in fields:
            row.scrape_status = fields["scrape_status"]
        if fields.get("site_total") is not None:
            row.site_total = fields["site_total"]

    @staticmethod
    def _max_pages_per_knowledge() -> int:
        """浅采时每个知识点最多翻几页，0 = 不限（正常深采）"""
        return max(0, int(getattr(config, "ZUJUAN_MAX_PAGES_PER_KNOWLEDGE", 0) or 0))

    @classmethod
    def _sweep_mode(cls) -> bool:
        """是不是浅采模式 —— 每个知识点翻几页就走，且不做超量切片。

        两者是绑定的：浅采的意义就是"广度优先铺一层底"，当场为某个知识点炸出
        一堆分片去挨个采，正好和这个目的相反。
        """
        return cls._max_pages_per_knowledge() > 0

    def _budget_exhausted(self) -> bool:
        budget = int(getattr(config, "ZUJUAN_MAX_QUESTIONS_PER_RUN", 0) or 0)
        return budget > 0 and self._saved_count >= budget

    @staticmethod
    async def _sleep_between(sleep_range, what: str) -> None:
        """在区间里随机取一个等待时长 —— 固定间隔本身就是机器特征"""
        try:
            low, high = float(sleep_range[0]), float(sleep_range[1])
        except (TypeError, ValueError, IndexError, KeyError):
            low, high = 2.0, 5.0
        if high < low:
            low, high = high, low
        seconds = random.uniform(low, high)
        utils.logger.info(f"[ZuJuanCrawler] Sleeping {seconds:.1f}s before {what}")
        await asyncio.sleep(seconds)

    # ------------------------------------------------------------------
    # 抓法三：人工翻页，脚本只负责入库
    # ------------------------------------------------------------------

    async def watch_manual_browsing(self) -> None:
        """
        人在浏览器里正常浏览，脚本把他停留的每一页解析入库。

        ★ 全程只读页面内容：不 goto、不 click、不注入任何输入事件，也不发 httpx
          请求。翻页、过验证全部由人在浏览器里完成 —— 脚本在这里的角色是记事本，
          不是浏览器。
        """
        interval = float(getattr(config, "ZUJUAN_WATCH_INTERVAL_SEC", 1.5))
        seen: set = set()
        idle_ticks = 0

        await self._load_watch_queue()
        utils.logger.info(
            f"[ZuJuanCrawler.watch] 人工翻页模式已启动，待采 {len(self._watch_queue)} 项。"
            " 翻到哪一页就入库哪一页；一个知识点采完会自动跳到下一个的起始页；按 Ctrl+C 结束。"
        )
        await self._open_current_target()

        while True:
            try:
                changed = await self._scan_open_pages(seen)
            except Exception as e:  # noqa: BLE001 - 监听不能因为单次异常退出
                utils.logger.warning(f"[ZuJuanCrawler.watch] 扫描页面出错: {e}")
                changed = 0

            if changed:
                idle_ticks = 0
            else:
                idle_ticks += 1
                # 每约 60 秒提示一次还活着，不刷屏
                if interval > 0 and idle_ticks % max(1, int(60 / interval)) == 0:
                    utils.logger.info(
                        f"[ZuJuanCrawler.watch] 等待翻页中…… 本次已入库 {self._saved_count} 道"
                    )
            await asyncio.sleep(interval)

    async def _scan_open_pages(self, seen: set) -> int:
        """扫一遍浏览器里所有标签页，把没处理过的组卷网列表页入库。返回处理了几页"""
        handled = 0
        for page in list(self.browser_context.pages):
            try:
                url = page.url
            except Exception:
                continue
            if not url or not url.startswith(ZUJUAN_HOST):
                continue

            parsed = slicing.parse_list_url(url)
            if parsed is None:
                # 不是列表页（首页、详情页、验证页跳转……），不管
                continue

            try:
                page_html = await page.content()
            except Exception:
                # 正在跳转时取不到内容属正常，下一轮再看
                continue

            status = page_status(page_html)
            if status is not PageStatus.OK:
                if (url, status.value) not in seen:
                    seen.add((url, status.value))
                    utils.logger.info(
                        f"[ZuJuanCrawler.watch] {url} 当前是 {status.value} 页面，"
                        f"等你在浏览器里处理完（脚本不会碰它）"
                    )
                continue

            signature = (url, first_question_id(page_html))
            if signature in seen:
                continue
            seen.add(signature)
            if len(seen) > 20000:
                seen.clear()

            await self._ingest_watched_page(parsed, page_html, url)
            handled += 1
        return handled

    async def _ingest_watched_page(self, parsed, page_html: str, url: str) -> None:
        """把人工翻到的这一页解析入库，并按同一套规则记进度"""
        label = parsed.knowledge_id + (f"/{parsed.slice_key}" if parsed.slice_key else "")
        site_total = self._extractor.extract_site_total(page_html)

        questions: List[ZujuanQuestion] = self._extractor.extract_questions(
            page_html, list_url=url, page=parsed.page
        )
        if questions:
            before = self._saved_count
            source_keyword_var.set(parsed.knowledge_id)
            await self._save_questions(questions, label, parsed.page)
            utils.logger.info(
                f"[ZuJuanCrawler.watch] ✅ {label} 第 {parsed.page} 页入库 "
                f"{self._saved_count - before} 道 / 站点共 {site_total} 道"
                f"（本次累计 {self._saved_count}）"
            )
        else:
            # ★ 这一页没有卡片，但"共计 N 道"照样要记下来 ——
            #   摸站点总数本来就是打开首页看一眼那个数字，不该要求页面上必须有题
            utils.logger.info(
                f"[ZuJuanCrawler.watch] {label} 第 {parsed.page} 页没有题目卡片，"
                f"站点共 {site_total} 道"
            )

        # 进度和自动模式写同一套表，人工翻的页同样会记进 covered_pages
        try:
            await self._write_watch_progress(parsed, site_total, has_questions=bool(questions))
            if questions:
                # ★ 每页都重算 collected（不是累加）—— 采集可以重跑，
                #   而且一题挂多个知识点，加法根本对不上
                collected = await progress.refresh_collected(parsed.knowledge_id)
                utils.logger.info(
                    f"[ZuJuanCrawler.watch]    {label} 库里现有 {collected} / 站点 {site_total} 道"
                    f"{self._missing_hint(parsed, site_total)}"
                )
            await self._advance_queue(parsed, site_total)
        except Exception as e:  # noqa: BLE001 - 记进度失败不能影响已经入库的题
            utils.logger.warning(f"[ZuJuanCrawler.watch] {label} 写进度失败: {e}")

    async def _write_watch_progress(
        self, parsed, site_total: Optional[int], has_questions: bool = True
    ) -> None:
        """
        人工翻页的进度写入，和自动模式共用同一套表。

        ★ 只累加 covered_pages / last_page / site_total，绝不把状态写成 done ——
          人翻到哪算哪，"这个知识点采完了"不能由某一页的入库动作来断言
        """
        cached = self._watch_progress_cache.get(parsed.knowledge_id)
        if cached is None:
            targets = await progress.fetch_leaf_targets(knowledge_ids=[parsed.knowledge_id])
            target = targets[0] if targets else progress.KnowledgeTarget(
                knowledge_id=parsed.knowledge_id
            )
            slices = await progress.fetch_slice_map(parsed.knowledge_id)
            cached = (target, slices)
            self._watch_progress_cache[parsed.knowledge_id] = cached
        target, slices = cached
        if not has_questions:
            # 只摸到一个总数、没拿到题：只更新 site_total，不能把这一页记成"采过了"
            if site_total is None:
                return
            if parsed.parts:
                await progress.save_slice_progress(
                    parsed.knowledge_id, parsed.slice_key, site_total=site_total
                )
            else:
                await progress.save_tree_progress(parsed.knowledge_id, site_total=site_total)
            return
        await self._write_page_progress(target, parsed.parts, slices, parsed.page, site_total)

    # ---- 待采队列：知识点 / 分片统一用一个队列表示 ----

    async def _load_watch_queue(self) -> None:
        """装载待采队列，顺序和自动模式一致：先收尾没采完的，再采没采过的"""
        knowledge_ids = [
            item.strip()
            for item in getattr(config, "ZUJUAN_KNOWLEDGE_ID_LIST", []) or []
            if item and item.strip()
        ]
        targets = await progress.fetch_leaf_targets(
            limit=int(getattr(config, "ZUJUAN_KNOWLEDGE_LIMIT", 0) or 0),
            knowledge_ids=knowledge_ids or None,
            bank_id=(getattr(config, "ZUJUAN_BANK_ID", "") or None),
        )
        self._watch_queue = []
        for target in targets:
            self._watch_progress_cache.setdefault(target.knowledge_id, (target, {}))
            self._watch_queue.append(WatchTarget(target.knowledge_id, {}, target.title))

        # 上次已经切开、但分片没采完的知识点，直接从没采完的那些片接着来
        for target in targets:
            if target.scrape_status != progress.STATUS_SLICING:
                continue
            slices = await progress.fetch_slice_map(target.knowledge_id)
            self._watch_progress_cache[target.knowledge_id] = (target, slices)
            pending = [
                key
                for key, row in slices.items()
                if row.scrape_status not in progress.TERMINAL_STATUS
                and row.scrape_status != progress.STATUS_SLICING
            ]
            if not pending:
                continue
            index = next(
                i for i, item in enumerate(self._watch_queue)
                if item.knowledge_id == target.knowledge_id and not item.parts
            )
            self._watch_queue[index:index + 1] = [
                WatchTarget(target.knowledge_id, slicing.parse_slice_key(key), target.title)
                for key in sorted(pending)
            ]

    def _current_target(self) -> Optional["WatchTarget"]:
        return self._watch_queue[0] if self._watch_queue else None

    def _progress_row(self, item: "WatchTarget"):
        """一个队列项对应的进度行：不带筛选条件是 knowledge_tree，带了是 knowledge_slice"""
        cached = self._watch_progress_cache.get(item.knowledge_id)
        if cached is None:
            return None
        target, slices = cached
        if not item.parts:
            return target
        return slices.get(item.slice_key)

    async def _open_current_target(self) -> None:
        """把浏览器带到当前该采的知识点/分片的续采页。

        ★ 这是 watch 模式下脚本唯一会做的导航动作，每个知识点/分片一次，相当于
          替你把地址粘进地址栏。翻页仍然全部由你操作。见 ZUJUAN_WATCH_AUTO_OPEN。
        """
        item = self._current_target()
        if item is None:
            utils.logger.info("[ZuJuanCrawler.watch] 队列已空，没有待采的知识点了")
            return

        row = self._progress_row(item)
        resume_page = row.resume_page if row is not None else 1
        site_total = row.site_total if row is not None else None
        base_url = slicing.build_list_url(item.knowledge_id, item.parts, prefix=self.url_prefix)
        page_url = build_page_url(base_url, resume_page, None)

        missing = slicing.missing_pages(
            row.covered_pages if row is not None else None, site_total
        )
        gap = f"，还缺 {len(missing)} 页：{self._format_page_list(missing)}" if missing else ""
        utils.logger.info(
            f"[ZuJuanCrawler.watch] ▶ 下一个：{item.label}"
            f"（剩 {len(self._watch_queue)} 项）从第 {resume_page} 页开始{gap} —— {page_url}"
        )
        if not getattr(config, "ZUJUAN_WATCH_AUTO_OPEN", True):
            utils.logger.info("[ZuJuanCrawler.watch]    （自动跳转已关，请自己打开上面这个地址）")
            return

        try:
            page = await self._watch_page()
            await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            await page.bring_to_front()
        except Exception as e:  # noqa: BLE001 - 跳转失败不致命，人可以自己打开
            utils.logger.warning(
                f"[ZuJuanCrawler.watch] 自动跳转失败({e})，请自己在浏览器里打开：{page_url}"
            )

    async def _watch_page(self):
        """拿一个用来跳转的标签页：优先复用已经开着的组卷网页，没有才新开一个"""
        for page in list(self.browser_context.pages):
            try:
                if page.url and page.url.startswith(ZUJUAN_HOST):
                    return page
            except Exception:
                continue
        if self._watch_nav_page is None or self._watch_nav_page.is_closed():
            self._watch_nav_page = await self.browser_context.new_page()
        return self._watch_nav_page

    @staticmethod
    def _format_page_list(pages: List[int], limit: int = 12) -> str:
        """页码列表打进日志，太长就只列前几个 —— 精确页码在 covered_pages 里"""
        if len(pages) <= limit:
            return ",".join(str(page) for page in pages)
        head = ",".join(str(page) for page in pages[:limit])
        return f"{head}… 共 {len(pages)} 页"

    def _missing_hint(self, parsed, site_total: Optional[int]) -> str:
        """给日志补一句"这一片还缺哪几页"，算不出来就什么都不说"""
        row = self._progress_row(WatchTarget(parsed.knowledge_id, parsed.parts, ""))
        if row is None:
            return ""
        missing = slicing.missing_pages(row.covered_pages, site_total)
        if not missing:
            return ""
        return f"，还缺 {len(missing)} 页：{self._format_page_list(missing)}"

    # ---- 队列推进：切片展开 / 完成 / 汇总 ----

    async def _advance_queue(self, parsed, site_total: Optional[int]) -> None:
        """
        每入库一页之后推进队列：这一片超硬顶就展开成子片，采满了就标 done 换下一个。

        ★ 用的判据和自动模式完全一样（slicing.exceeds_hard_cap / is_fully_covered），
          只是"翻页"这个动作由人来做，脚本只负责定位到下一个该看的地址。
        """
        index = self._queue_index(parsed.knowledge_id, slicing.slice_key(parsed.parts))
        if index is None:
            return
        item = self._watch_queue[index]
        head_before = self._watch_queue[0]

        if slicing.exceeds_hard_cap(site_total):
            await self._expand_into_slices(index, item, site_total)
        elif slicing.is_fully_covered(self._covered_of(item), site_total):
            await self._finish_item(index, item, site_total)
        else:
            return

        if self._watch_queue and self._watch_queue[0] is not head_before:
            await self._open_current_target()
        elif not self._watch_queue:
            await self._open_current_target()

    def _queue_index(self, knowledge_id: str, slice_key: str) -> Optional[int]:
        for index, item in enumerate(self._watch_queue):
            if item.knowledge_id == knowledge_id and item.slice_key == slice_key:
                return index
        return None

    def _covered_of(self, item: "WatchTarget") -> Optional[str]:
        row = self._progress_row(item)
        return row.covered_pages if row is not None else None

    async def _expand_into_slices(
        self, index: int, item: "WatchTarget", site_total: Optional[int]
    ) -> None:
        """
        这一片超过翻页硬顶 —— 就地展开成下一维的若干子片，插回队列原位。

        ★ 按需展开，不预先铺开：只有真的超了才往下切一维，切出来的子片各自再判。
          维度顺序和自动模式一致：题型 -> 难度 -> 解答题子题型 -> 年份。
        """
        dim = slicing.next_dim(item.parts)
        if dim is None:
            note = (
                f"切到底仍超硬顶：站点 {site_total} 道，翻页最多拿到 {slicing.HARD_CAP} 道"
            )
            utils.logger.error(f"[ZuJuanCrawler.watch] ✖ {item.label} {note}")
            await self._save_item_status(item, progress.STATUS_CAPPED, note=note[:255])
            self._watch_queue.pop(index)
            await self._maybe_rollup(item.knowledge_id)
            return

        values = slicing.DIM_VALUES[dim]
        utils.logger.warning(
            f"[ZuJuanCrawler.watch] ⚠ {item.label} 站点共 {site_total} 道，超过翻页硬顶 "
            f"{slicing.HARD_CAP}（999 页 × 10）—— 一页页翻**永远采不完**。"
            f"已按{dim}切成 {len(values)} 片，会逐片带你过去："
        )
        children = []
        for value in values:
            parts = dict(item.parts)
            parts[dim] = value.code
            child = WatchTarget(item.knowledge_id, parts, item.title)
            children.append(child)
            url = slicing.build_list_url(item.knowledge_id, parts, prefix=self.url_prefix)
            utils.logger.warning(f"[ZuJuanCrawler.watch]     {slicing.slice_name(parts):<22} {url}")

        await self._save_item_status(item, progress.STATUS_SLICING, site_total=site_total)
        self._watch_queue[index:index + 1] = children

    async def _finish_item(
        self, index: int, item: "WatchTarget", site_total: Optional[int]
    ) -> None:
        """页码覆盖满了：标 done、重算 collected、弹出队列，必要时汇总到知识点"""
        await self._save_item_status(item, progress.STATUS_DONE)
        if item.parts:
            collected = await progress.refresh_slice_collected(
                item.knowledge_id, item.slice_key
            )
        else:
            collected = await progress.refresh_collected(item.knowledge_id)
        utils.logger.info(
            f"[ZuJuanCrawler.watch] ✔ {item.label} 采完了"
            f"（站点 {site_total} / 库里 {collected}），状态已写 done"
        )
        self._watch_queue.pop(index)
        await self._maybe_rollup(item.knowledge_id)

    async def _save_item_status(self, item: "WatchTarget", status: str, **extra) -> None:
        row = self._progress_row(item)
        if row is not None:
            row.scrape_status = status
            if extra.get("site_total") is not None:
                row.site_total = extra["site_total"]
        if item.parts:
            await progress.save_slice_progress(
                item.knowledge_id,
                item.slice_key,
                dim=slicing.current_dim(item.parts),
                slice_name=slicing.slice_name(item.parts),
                depth=slicing.dim_depth(slicing.current_dim(item.parts)),
                scrape_status=status,
                **{k: v for k, v in extra.items() if v is not None},
            )
        else:
            await progress.save_tree_progress(
                item.knowledge_id,
                scrape_status=status,
                **{k: v for k, v in extra.items() if v is not None},
            )

    async def _maybe_rollup(self, knowledge_id: str) -> None:
        """一个知识点的分片全处理完了，把状态汇总回 knowledge_tree"""
        if any(item.knowledge_id == knowledge_id for item in self._watch_queue):
            return
        cached = self._watch_progress_cache.get(knowledge_id)
        if cached is None:
            return
        target, slices = cached
        if target.scrape_status == progress.STATUS_DONE:
            return
        # 只要有一片是 capped，整个知识点也标 capped —— 让人知道确实有一部分拿不全
        rolled = (
            progress.STATUS_CAPPED
            if any(row.scrape_status == progress.STATUS_CAPPED for row in slices.values())
            else progress.STATUS_DONE
        )
        target.scrape_status = rolled
        await progress.save_tree_progress(knowledge_id, scrape_status=rolled)
        collected = await progress.refresh_collected(knowledge_id)
        utils.logger.info(
            f"[ZuJuanCrawler.watch] ✔ {knowledge_id}「{target.title}」全部分片处理完，"
            f"汇总状态 {rolled}，库里 {collected} 道"
        )


    # ------------------------------------------------------------------
    # 抓法二：按写死的列表页 URL
    # ------------------------------------------------------------------

    async def crawl_by_url(self) -> None:
        """按配置的列表页 URL 抓题，自动翻页。不写 knowledge_tree 进度"""
        list_urls: List[str] = [url.strip() for url in config.ZUJUAN_SPECIFIED_URL_LIST if url.strip()]
        if not list_urls:
            utils.logger.error(
                "[ZuJuanCrawler.crawl_by_url] 没有配置列表页 URL，"
                "请在 config/zujuan_config.py 的 ZUJUAN_SPECIFIED_URL_LIST 中填写，"
                "或用 --specified_id 传入"
            )
            return

        for list_url in list_urls:
            utils.logger.info(f"[ZuJuanCrawler.crawl_by_url] Begin crawl list url: {list_url}")
            source_keyword_var.set(list_url)
            try:
                await self.crawl_list_url(list_url)
            except Exception as e:
                utils.logger.error(f"[ZuJuanCrawler.crawl_by_url] Crawl list url {list_url} failed: {e}")

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
            page_html = await self.zujuan_client.get_page_html(
                page_url, referer=list_url, page_no=page, base_url=list_url
            )

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
                if not question.question_id:
                    # 卡片在但抽不到 ID，属于"数量悄悄变少"型故障，必须留痕
                    utils.logger.warning(
                        f"[ZuJuanCrawler.crawl_list_url] 第 {page} 页有一张卡片抽不到 question_id，已跳过"
                    )
                    continue
                if not question.stem_html:
                    # ★抽到了 ID 却没抽到题干，不是"这题没题干"，而是选择器可能失效了。
                    #   这种半成品单独告警，不能当正常数据混进去
                    utils.logger.warning(
                        f"[ZuJuanCrawler.crawl_list_url] question_id {question.question_id} "
                        f"抽到了 ID 但题干为空，疑似选择器失效，请检查页面结构"
                    )
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
            await self._sleep_between(
                getattr(config, "ZUJUAN_PAGE_SLEEP_RANGE", (2.0, 5.0)), f"page {page}"
            )

    async def create_zujuan_client(self, httpx_proxy: Optional[str]) -> ZuJuanClient:
        """用浏览器里已经过完挑战的 Cookie 和**真实指纹**创建 httpx 客户端"""
        # ★ 只取组卷网这个域的 Cookie。不带 urls 时 Playwright 会返回整个上下文里
        #   所有域的 Cookie —— CDP 接管的是用户真实的 Chrome，那等于把用户其它网站
        #   的登录态发给组卷网
        cookie_str, _ = utils.convert_cookies(
            await self.browser_context.cookies(urls=[self.index_url])
        )

        user_agent, client_hints = await self._read_browser_fingerprint()
        zujuan_client = ZuJuanClient(
            timeout=30,
            user_agent=user_agent,
            cookie_str=cookie_str,
            proxy=httpx_proxy,
            playwright_page=self.context_page,
            client_hints=client_hints,
        )
        zujuan_client.init_proxy_pool(self.ip_proxy_pool)
        return zujuan_client

    async def _read_browser_fingerprint(self):
        """
        从页面里读浏览器真实的 UA 和 client hints。

        ★ 不能用 utils.get_user_agent() 那个随机假 UA：CDP 接管已有 Chrome 时，
          CDPBrowserManager._create_browser_context() 复用的是 browser.contexts[0]，
          传进去的 user_agent 参数**被静默忽略**，浏览器用的始终是它自己的真 UA。
          人在浏览器里过完滑块，WAF 把凭证绑定到那个真实指纹上；httpx 换个假 UA
          拿同一张凭证去请求，WAF 判定凭证被盗用，立刻重新弹验证 —— 表现就是
          "手动过一次就好，脚本每翻一页都要拖滑块"
        """
        user_agent = self.user_agent
        client_hints = {}
        try:
            user_agent = await self.context_page.evaluate("() => navigator.userAgent")
            ua_data = await self.context_page.evaluate(
                "() => navigator.userAgentData ? {"
                " brands: navigator.userAgentData.brands,"
                " mobile: navigator.userAgentData.mobile,"
                " platform: navigator.userAgentData.platform } : null"
            )
            client_hints = client_hints_from_page_data(ua_data)
        except Exception as e:  # noqa: BLE001 - 读不到就退回构造时那个，只是不够像
            utils.logger.warning(
                f"[ZuJuanCrawler] 读取浏览器真实 UA 失败({e})，退回 {user_agent}"
            )
        self.user_agent = user_agent
        utils.logger.info(
            f"[ZuJuanCrawler] httpx 将使用与浏览器一致的 UA: {user_agent}"
            f"{'（含 client hints）' if client_hints else ''}"
        )
        return user_agent, client_hints

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
        client = getattr(self, "zujuan_client", None)
        if client is not None:
            # 长生命周期的 httpx client 持着 Cookie jar 和连接池，要显式关
            await client.close()
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        elif self.browser_context:
            await self.browser_context.close()
        utils.logger.info("[ZuJuanCrawler.close] Browser context closed ...")
