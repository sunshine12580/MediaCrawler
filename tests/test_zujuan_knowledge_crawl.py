# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_zujuan_knowledge_crawl.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
按知识点抓取的流程单测（docs/zujuan/知识点切片抓取规范.md）。

守两类问题：

1. **进度列白名单** —— knowledge_tree 是共享表，树结构那组列归"知识点树同步"
   那条线，写进去会把人家的产物冲掉。
2. **翻页硬顶检测** —— 第 1000 页起站点把第 999 页原样重复返回，不报错也不空页。
   漏检的表现是"程序一直在跑但入库数不涨"，是最难发现的一类故障。
"""
import asyncio
import pathlib

import pytest

import config

from media_platform.zujuan import slicing
from media_platform.zujuan.core import WatchTarget, ZuJuanCrawler
from store.zujuan import _progress as progress

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ----------------------------- 进度列白名单 -----------------------------

def test_tree_progress_columns_exclude_tree_structure():
    """树结构列一列都不能出现在本项目的写入白名单里"""
    structure_columns = {
        "node_id", "bank_id", "title", "parent_id", "level",
        "path", "href", "is_knowledge", "child_count", "sort_ord", "updated_at",
    }
    assert not (progress.TREE_PROGRESS_COLUMNS & structure_columns)


@pytest.mark.parametrize("column", ["title", "path", "parent_id", "child_count", "updated_at"])
def test_save_tree_progress_rejects_structure_columns(column):
    with pytest.raises(ValueError, match="拒绝写 knowledge_tree"):
        asyncio.run(progress.save_tree_progress("zsd4700", **{column: "x"}))


def test_save_slice_progress_rejects_unknown_columns():
    with pytest.raises(ValueError, match="拒绝写 knowledge_slice"):
        asyncio.run(progress.save_slice_progress("zsd4700", "t1", nonsense=1))


# ----------------------------- recount 口径 -----------------------------

def test_slice_conditions_use_difficulty_band_not_difficulty_code():
    """★ 站点的 d1/d2/d3 对应库里由得分率重算的 difficulty_band（3 档），
    不是按钮上的 difficulty_code（5 档）—— 两套编码数值会撞车"""
    conditions = progress.slice_conditions(slicing.parse_slice_key("t4d1s1"))
    rendered = [str(condition) for condition in conditions]
    assert any("qtype_code" in text for text in rendered)
    assert any("difficulty_band" in text for text in rendered)
    assert not any("difficulty_code" in text for text in rendered)
    assert any("qtype_sub" in text for text in rendered)


def test_slice_conditions_year_earlier_bucket_is_a_range():
    """y-1 是"比 2020 还早"这一段范围，不是某一年"""
    assert str(progress.slice_conditions({"year": "y2025"})[0]).find("=") > 0
    assert "<" in str(progress.slice_conditions({"year": "y-1"})[0])


# ----------------------------- 子片状态汇总 -----------------------------

def test_roll_up_any_capped_makes_parent_capped():
    """只要有一片拿不全，父片也要标 capped，不能显示成'采完了'"""
    assert ZuJuanCrawler._roll_up(["done", "done", "capped"], 3) == progress.STATUS_CAPPED


def test_roll_up_all_finished_is_done():
    assert ZuJuanCrawler._roll_up(["done", "empty", "done"], 3) == progress.STATUS_DONE


def test_roll_up_incomplete_stays_slicing():
    # 少跑了一片（比如本次预算用完了），保留 slicing 下次接着切
    assert ZuJuanCrawler._roll_up(["done", "done"], 3) == progress.STATUS_SLICING
    # 有一片自己还没翻完
    assert ZuJuanCrawler._roll_up(["done", "partial", "done"], 3) == progress.STATUS_SLICING


# ----------------------------- 翻页 -----------------------------

class _FakePage:
    """一页假 HTML：站点报的总数 + 这一页的题目 ID"""

    def __init__(self, site_total, question_ids):
        self.site_total = site_total
        self.question_ids = question_ids


class _FakeQuestion:
    def __init__(self, question_id):
        self.question_id = question_id
        self.stem_html = "<p>题干</p>"


class _FakeExtractor:
    def __init__(self, pages):
        self.pages = pages

    def _page(self, marker):
        # marker 是 "页索引.第几次请求" —— 次数由 client 记，不能在这里自增：
        # 每取一页会分别调用 extract_site_total 和 extract_questions 两次
        index, _, attempt = str(marker).partition(".")
        entry = self.pages[int(index)]
        if isinstance(entry, list):
            # 同一页被重复请求时依次返回不同的响应，用来模拟"第一次没渲染完、
            # 重取一次就有卡片了"。取完了就一直返回最后一项
            return entry[min(int(attempt or 0), len(entry) - 1)]
        return entry

    def extract_page_url_template(self, page_html):
        return None

    def extract_site_total(self, page_html):
        return self._page(page_html).site_total

    def extract_questions(self, page_html, list_url="", page=1):
        return [_FakeQuestion(qid) for qid in self._page(page_html).question_ids]


class _FakeClient:
    """按请求到的页码返回对应的假页面。

    签名要和真 client 一致 —— 爬虫会把 page_no/base_url 一起传下去，好让
    client 决定是"点分页器"还是直接 goto"""

    def __init__(self):
        self.requested = []
        self.base_urls = []
        self._attempts = {}

    async def get_page_html(self, url, referer="", page_no=None, base_url=""):
        self.requested.append(page_no)
        self.base_urls.append(base_url)
        index = (page_no or 1) - 1
        attempt = self._attempts.get(index, 0)
        self._attempts[index] = attempt + 1
        return f"{index}.{attempt}"


def _run_page_through(pages, start_page=1):
    crawler = ZuJuanCrawler()
    crawler._extractor = _FakeExtractor(pages)
    crawler.zujuan_client = _FakeClient()
    saved = []

    async def fake_save(questions, label, page):
        saved.extend(question.question_id for question in questions)
        return len(questions)

    async def fake_write(target, parts, slices, page, site_total):
        return None

    async def fake_sleep(sleep_range, what):
        return None

    crawler._save_questions = fake_save
    crawler._write_page_progress = fake_write
    crawler._sleep_between = fake_sleep

    target = progress.KnowledgeTarget(knowledge_id="zsd4700", title="测试")
    outcome, site_total = asyncio.run(
        crawler._page_through(target, {}, {}, start_page)
    )
    return outcome, site_total, saved, crawler.zujuan_client.requested


def test_page_through_finishes_by_page_coverage():
    """按页码覆盖规则收尾：站点报 25 道 = 3 页，翻完第 3 页就是 done"""
    pages = [
        _FakePage(25, ["a1", "a2"]),
        _FakePage(25, ["b1", "b2"]),
        _FakePage(25, ["c1", "c2"]),
    ]
    outcome, site_total, saved, requested = _run_page_through(pages)
    assert outcome is slicing.SliceOutcome.DONE
    assert site_total == 25
    assert requested == [1, 2, 3]
    assert saved == ["a1", "a2", "b1", "b2", "c1", "c2"]


def test_page_through_stops_on_empty_page():
    """翻到站点报的最后一页之后还是空 = 正常翻到底，不是撞硬顶"""
    pages = [_FakePage(15, ["a1"]), _FakePage(15, [])]
    outcome, _, saved, requested = _run_page_through(pages)
    assert outcome is slicing.SliceOutcome.DONE
    assert requested == [1, 2]
    assert saved == ["a1"]


def test_empty_page_before_last_page_is_not_done():
    """★ 线上 zsd6026 的真实故障：site_total=656（66 页），第 9 页读回来是空的，
    旧逻辑直接标 done —— 一个才翻了 8 页的知识点被记成"采完了"，剩下的 57 页
    再也不会被采集，而且不报错。

    站点说还有页 + 这一页没卡片 = 两个数据自相矛盾，只能保留 partial 下次重试。
    """
    pages = [_FakePage(656, ["a1"]), _FakePage(656, [])]
    outcome, site_total, saved, requested = _run_page_through(pages)
    assert outcome is slicing.SliceOutcome.INTERRUPTED
    assert outcome.value == "partial"
    assert site_total == 656
    assert saved == ["a1"]
    # 第 2 页被重取了 EMPTY_PAGE_RETRY 次
    assert requested == [1, 2, 2, 2]


def test_empty_page_at_hard_cap_slices_instead_of_done():
    """★ total_pages() 封顶 999，超硬顶的片翻到第 999 页读回来是空的，
    那是翻到了硬顶而不是采完了 —— 必须转切片。线上有 3 条 last_page=999
    的分片就是这么被标成 done 的"""
    # 第 1 页站点报 9990 道（正好不超硬顶，所以不会一上来就切片），
    # 翻到第 999 页时站点已经涨到 9991 道，而这一页读回来是空的
    pages = [_FakePage(slicing.HARD_CAP, [f"q{page}"]) for page in range(1, slicing.MAX_PAGE)]
    pages.append(_FakePage(slicing.HARD_CAP + 1, []))
    outcome, site_total, _, _ = _run_page_through(pages)
    assert outcome is slicing.SliceOutcome.NEED_SLICE
    assert site_total == slicing.HARD_CAP + 1


def test_empty_page_recovers_after_refetch():
    """网慢导致的空页重取一次就有了，应该接着往下翻而不是中断"""
    pages = [
        _FakePage(25, ["a1"]),
        [_FakePage(25, []), _FakePage(25, ["b1"])],
        _FakePage(25, ["c1"]),
    ]
    outcome, _, saved, requested = _run_page_through(pages)
    assert outcome is slicing.SliceOutcome.DONE
    assert saved == ["a1", "b1", "c1"]
    # 第 2 页取了两次（第一次空，重取拿到），第 3 页正常
    assert requested == [1, 2, 2, 3]


def test_empty_page_uses_refreshed_total_to_decide():
    """重取时站点报的题数变小了，按新的页数判 —— 25 道只有 3 页，
    第 3 页空了就是真的到头，不该再无限重试"""
    pages = [
        _FakePage(1000, ["a1"]),
        _FakePage(1000, ["b1"]),
        [_FakePage(25, []), _FakePage(25, [])],
    ]
    outcome, site_total, saved, _ = _run_page_through(pages)
    assert outcome is slicing.SliceOutcome.DONE
    assert site_total == 25
    assert saved == ["a1", "b1"]


def test_empty_page_turning_zero_is_empty_not_done():
    """重取时站点改口说这里没题 —— 记 empty，别记成 done + site_total=0"""
    pages = [_FakePage(500, ["a1"]), [_FakePage(0, []), _FakePage(0, [])]]
    outcome, site_total, _, _ = _run_page_through(pages)
    assert outcome is slicing.SliceOutcome.EMPTY
    assert site_total == 0


def test_sweep_empty_page_before_last_page_is_not_done(sweep):
    """浅采下同样不能把空页当翻到底 —— 这正是线上 zsd6026 被标 done 的场景"""
    sweep(5)
    pages = [_FakePage(656, ["a1"]), _FakePage(656, [])]
    outcome, _, _, _ = _run_page_through(pages)
    assert outcome is slicing.SliceOutcome.INTERRUPTED


def test_page_through_detects_hard_cap_by_repeated_ids():
    """★ 第 2 页和第 1 页题目完全相同 = 站点在重复返回，必须停下来转切片"""
    pages = [_FakePage(50, ["a1", "a2"]), _FakePage(50, ["a1", "a2"])]
    outcome, _, saved, _ = _run_page_through(pages)
    assert outcome is slicing.SliceOutcome.NEED_SLICE
    # 重复的那一页不能再入一次库
    assert saved == ["a1", "a2"]


def test_page_through_switches_to_slicing_on_first_read():
    """超过硬顶就在读到数字的第一时间转切片，不用傻等翻到第 999 页"""
    pages = [_FakePage(24003, ["a1"])]
    outcome, site_total, saved, requested = _run_page_through(pages)
    assert outcome is slicing.SliceOutcome.NEED_SLICE
    assert site_total == 24003
    assert requested == [1]
    assert saved == []


def test_page_through_zero_total_is_empty():
    outcome, site_total, saved, _ = _run_page_through([_FakePage(0, [])])
    assert outcome is slicing.SliceOutcome.EMPTY
    assert site_total == 0
    assert saved == []


def test_page_through_unreadable_total_keeps_unfinished_state():
    """★ 读不到「共计 N 道」不能当成翻完了 —— 误判的代价是这个知识点后面的题
    永远不会再被采集"""
    pages = [_FakePage(50, ["a1"]), _FakePage(None, [])]
    outcome, _, saved, requested = _run_page_through(pages)
    assert outcome is slicing.SliceOutcome.INTERRUPTED
    assert requested == [1, 2]
    assert saved == ["a1"]


def test_page_through_resumes_from_given_page():
    pages = [
        _FakePage(25, ["a1"]),
        _FakePage(25, ["b1"]),
        _FakePage(25, ["c1"]),
    ]
    outcome, _, saved, requested = _run_page_through(pages, start_page=3)
    assert outcome is slicing.SliceOutcome.DONE
    assert requested == [3]
    assert saved == ["c1"]


def test_resume_page_prefers_covered_pages_gap():
    """线上 zsd5930 的真实数据：last_page 比 covered_pages 的上界大 36 页"""
    target = progress.KnowledgeTarget(
        knowledge_id="zsd5930", last_page=317, covered_pages="1-281"
    )
    assert target.resume_page == 282

    row = progress.SliceProgress(knowledge_id="zsd4718", slice_key="t4d1", last_page=629)
    assert row.resume_page == 630


# ----------------------------- 导入顺序 -----------------------------

@pytest.mark.parametrize(
    "first, second",
    [
        ("store.zujuan._progress", "media_platform.zujuan.core"),
        ("media_platform.zujuan.core", "store.zujuan._progress"),
    ],
)
def test_import_order_both_ways(first, second):
    """★ 爬虫要写进度、进度层要用切片维度定义，两个模块互相依赖。
    谁先被 import 谁就拿到对方的半成品，core.py 靠推迟注解求值化解 ——
    这里把两个方向都锁住，免得以后有人在 core 的模块层直接取 progress.X 又炸回来"""
    import subprocess
    import sys

    code = f"import {first}; import {second}; print('ok')"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT)
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


# ----------------------------- 空值保护 -----------------------------

def test_write_progress_drops_null_site_total():
    """★ 被拦截时 site_total 是 None，不能拿 NULL 把上次读到的数冲掉"""
    crawler = ZuJuanCrawler()
    captured = {}

    async def fake_save(knowledge_id, **fields):
        captured.update(fields)

    original = progress.save_tree_progress
    progress.save_tree_progress = fake_save
    try:
        target = progress.KnowledgeTarget(knowledge_id="zsd4700")
        asyncio.run(
            crawler._write_progress(
                target, {}, {}, scrape_status="partial", site_total=None
            )
        )
    finally:
        progress.save_tree_progress = original

    assert "site_total" not in captured
    assert captured["scrape_status"] == "partial"


def test_page_number_is_passed_down_for_click_paging():
    """★ 爬虫必须把页码和这一片的首页 URL 传给 client，否则 client 没法判断
    能不能接着点分页器，只能退化成每页 goto 一个深链接"""
    pages = [_FakePage(25, ["a1"]), _FakePage(25, ["b1"]), _FakePage(25, ["c1"])]
    crawler = ZuJuanCrawler()
    crawler._extractor = _FakeExtractor(pages)
    crawler.zujuan_client = _FakeClient()

    async def noop(*args, **kwargs):
        return None

    crawler._save_questions = noop
    crawler._write_page_progress = noop
    crawler._sleep_between = noop

    target = progress.KnowledgeTarget(knowledge_id="zsd4700")
    asyncio.run(crawler._page_through(target, {}, {}, 1))

    assert crawler.zujuan_client.requested == [1, 2, 3]
    assert set(crawler.zujuan_client.base_urls) == {
        "https://zujuan.xkw.com/czsx/zsd4700/o2/"
    }


# ---------------------------------------------------------------------------
# 人工翻页模式：人在浏览器里翻，脚本只入库
# ---------------------------------------------------------------------------


class _WatchPage:
    """假标签页，只提供 url 和 content —— watch 模式不该用到别的任何方法"""

    def __init__(self, url, html):
        self.url = url
        self._html = html

    async def content(self):
        return self._html


class _WatchContext:
    def __init__(self, pages):
        self.pages = pages


def _make_watch_crawler(pages, extractor_pages=None):
    crawler = ZuJuanCrawler()
    crawler.browser_context = _WatchContext(pages)
    return crawler


LIST_HTML = (
    '<em class="ques-sum" id="questioncount">1,234</em>'
    '<div class="tk-quest-item" questionid="777">题</div>'
)


class _WatchExtractor:
    def __init__(self):
        self.calls = []

    def extract_questions(self, page_html, list_url="", page=1):
        self.calls.append((list_url, page))
        return [_FakeQuestion("777")]

    def extract_site_total(self, page_html):
        return 1234


def _run_scan(crawler, seen=None):
    saved = []
    progress_writes = []

    async def fake_save(questions, label, page):
        saved.append((label, page, [q.question_id for q in questions]))
        crawler._saved_count += len(questions)

    async def fake_progress(parsed, site_total, has_questions=True):
        progress_writes.append(
            (parsed.knowledge_id, parsed.slice_key, parsed.page, site_total, has_questions)
        )

    crawler._save_questions = fake_save
    crawler._write_watch_progress = fake_progress
    handled = asyncio.run(crawler._scan_open_pages(seen if seen is not None else set()))
    return handled, saved, progress_writes


def test_watch_ingests_the_page_the_human_is_on():
    crawler = _make_watch_crawler(
        [_WatchPage("https://zujuan.xkw.com/czsx/zsd5501/qt1103d1o2p387/", LIST_HTML)]
    )
    crawler._extractor = _WatchExtractor()

    handled, saved, writes = _run_scan(crawler)

    assert handled == 1
    assert saved == [("zsd5501/t4d1", 387, ["777"])]
    assert writes == [("zsd5501", "t4d1", 387, 1234, True)]


def test_watch_ignores_non_list_tabs():
    """人开着的别的标签页一律不碰"""
    crawler = _make_watch_crawler(
        [
            _WatchPage("https://zujuan.xkw.com/", LIST_HTML),
            _WatchPage("https://mail.google.com/", LIST_HTML),
            _WatchPage("https://zujuan.xkw.com/czsx/zsd5501/", LIST_HTML),
        ]
    )
    crawler._extractor = _WatchExtractor()

    handled, saved, writes = _run_scan(crawler)

    assert handled == 0
    assert saved == []


def test_watch_does_not_touch_captcha_pages():
    """★ 验证页只提示、不解析 —— 这是人的活，脚本不碰"""
    captcha = '<div class="nc-container">请拖动滑块</div>'
    crawler = _make_watch_crawler(
        [_WatchPage("https://zujuan.xkw.com/czsx/zsd5501/o2p2/", captcha)]
    )
    crawler._extractor = _WatchExtractor()

    handled, saved, _ = _run_scan(crawler)

    assert handled == 0
    assert saved == []


def test_watch_does_not_reingest_the_same_page():
    """人停在同一页不动，不能反复入库"""
    crawler = _make_watch_crawler(
        [_WatchPage("https://zujuan.xkw.com/czsx/zsd5501/o2p2/", LIST_HTML)]
    )
    crawler._extractor = _WatchExtractor()
    seen = set()

    first, saved1, _ = _run_scan(crawler, seen)
    second, saved2, _ = _run_scan(crawler, seen)

    assert first == 1 and len(saved1) == 1
    assert second == 0 and saved2 == []


def test_watch_handles_several_tabs_at_once():
    crawler = _make_watch_crawler(
        [
            _WatchPage("https://zujuan.xkw.com/czsx/zsd5501/o2p2/", LIST_HTML),
            _WatchPage(
                "https://zujuan.xkw.com/czsx/zsd4774/qt1101o2p9/",
                LIST_HTML.replace('questionid="777"', 'questionid="888"'),
            ),
        ]
    )
    crawler._extractor = _WatchExtractor()

    handled, saved, writes = _run_scan(crawler)

    assert handled == 2
    assert {w[0] for w in writes} == {"zsd5501", "zsd4774"}


def test_watch_never_downgrades_a_finished_knowledge_point():
    """★ 人重新浏览一个已经 done 的知识点，不能把它打回 partial"""
    crawler = ZuJuanCrawler()
    captured = {}

    async def fake_save(knowledge_id, **fields):
        captured.update(fields)

    original = progress.save_tree_progress
    progress.save_tree_progress = fake_save
    try:
        done_target = progress.KnowledgeTarget(
            knowledge_id="zsd5501", scrape_status=progress.STATUS_DONE
        )
        asyncio.run(crawler._write_page_progress(done_target, {}, {}, 5, 1234))
    finally:
        progress.save_tree_progress = original

    assert "scrape_status" not in captured        # 状态原封不动
    assert captured["covered_pages"] == "5"       # 但页码照记
    assert captured["site_total"] == 1234
    assert done_target.scrape_status == progress.STATUS_DONE


def test_watch_records_site_total_even_when_page_has_no_questions():
    """★ 摸站点总数就是打开首页看一眼那个数字，不该要求页面上必须有题。
    但没拿到题时不能把这一页记成'采过了'"""
    empty_html = '<em class="ques-sum" id="questioncount">0</em>'

    class _EmptyExtractor(_WatchExtractor):
        def extract_questions(self, page_html, list_url="", page=1):
            return []

        def extract_site_total(self, page_html):
            return 42

    crawler = _make_watch_crawler(
        [_WatchPage("https://zujuan.xkw.com/czsx/zsd5970/o2/", empty_html)]
    )
    crawler._extractor = _EmptyExtractor()

    handled, saved, writes = _run_scan(crawler)

    assert handled == 1
    assert saved == []                                  # 没题可入库
    assert writes == [("zsd5970", "", 1, 42, False)]     # 但总数记下来了


def test_survey_write_only_touches_site_total():
    """★ 只摸总数时，绝不能顺手把 covered_pages / scrape_status 也改了"""
    crawler = ZuJuanCrawler()
    captured = {}

    async def fake_save(knowledge_id, **fields):
        captured.update(fields)

    parsed = slicing.parse_list_url("https://zujuan.xkw.com/czsx/zsd5970/o2/")
    crawler._watch_progress_cache[parsed.knowledge_id] = (
        progress.KnowledgeTarget(knowledge_id=parsed.knowledge_id), {}
    )

    original = progress.save_tree_progress
    progress.save_tree_progress = fake_save
    try:
        asyncio.run(crawler._write_watch_progress(parsed, 42, has_questions=False))
    finally:
        progress.save_tree_progress = original

    assert captured["site_total"] == 42
    assert "covered_pages" not in captured
    assert "last_page" not in captured
    assert "scrape_status" not in captured


# ---------------------------------------------------------------------------
# 人工翻页模式：队列推进与完成判定
# ---------------------------------------------------------------------------


class _NavPage:
    def __init__(self, url="https://zujuan.xkw.com/"):
        self.url = url
        self.goto_urls = []
        self.fronted = 0

    async def goto(self, url, **kwargs):
        self.goto_urls.append(url)
        self.url = url

    async def bring_to_front(self):
        self.fronted += 1

    def is_closed(self):
        return False


def _watch_crawler_with_queue(targets, nav_page):
    """targets 是 KnowledgeTarget（进度行），队列里放对应的 WatchTarget"""
    crawler = ZuJuanCrawler()
    crawler.browser_context = _WatchContext([nav_page])
    crawler._watch_queue = [WatchTarget(t.knowledge_id, {}, t.title) for t in targets]
    for t in targets:
        crawler._watch_progress_cache[t.knowledge_id] = (t, {})
    return crawler


def test_watch_opens_the_first_target_at_its_resume_page():
    """★ 启动时把浏览器带到第一个待采知识点的**续采页**，不是第 1 页"""
    nav = _NavPage()
    target = progress.KnowledgeTarget(
        knowledge_id="zsd5930", title="总体样本", last_page=317, covered_pages="1-281"
    )
    crawler = _watch_crawler_with_queue([target], nav)

    asyncio.run(crawler._open_current_target())

    assert nav.goto_urls == ["https://zujuan.xkw.com/czsx/zsd5930/o2p282/"]
    assert nav.fronted == 1


def test_watch_auto_open_can_be_switched_off():
    nav = _NavPage()
    crawler = _watch_crawler_with_queue(
        [progress.KnowledgeTarget(knowledge_id="zsd1")], nav
    )
    original = getattr(config, "ZUJUAN_WATCH_AUTO_OPEN", True)
    config.ZUJUAN_WATCH_AUTO_OPEN = False
    try:
        asyncio.run(crawler._open_current_target())
    finally:
        config.ZUJUAN_WATCH_AUTO_OPEN = original
    assert nav.goto_urls == []


def _stub_progress(saved, recounts, slice_saved=None):
    """把进度层的四个写入口换成记录器，返回还原用的闭包"""
    async def fake_tree(kid, **fields):
        saved.append((kid, fields))

    async def fake_slice(kid, key, **fields):
        (slice_saved if slice_saved is not None else saved).append((kid, key, fields))

    async def fake_recount(kid):
        recounts.append(kid)
        return 999

    async def fake_slice_recount(kid, key):
        recounts.append(f"{kid}/{key}")
        return 999

    originals = (
        progress.save_tree_progress, progress.save_slice_progress,
        progress.refresh_collected, progress.refresh_slice_collected,
    )
    progress.save_tree_progress = fake_tree
    progress.save_slice_progress = fake_slice
    progress.refresh_collected = fake_recount
    progress.refresh_slice_collected = fake_slice_recount

    def restore():
        (progress.save_tree_progress, progress.save_slice_progress,
         progress.refresh_collected, progress.refresh_slice_collected) = originals

    return restore


def _advance(crawler, knowledge_id, site_total, slice_key="", saved=None, recounts=None,
             slice_saved=None):
    parts = slicing.parse_slice_key(slice_key)
    url = slicing.build_list_url(knowledge_id, parts)
    parsed = slicing.parse_list_url(url)
    restore = _stub_progress(saved if saved is not None else [],
                             recounts if recounts is not None else [], slice_saved)
    try:
        asyncio.run(crawler._advance_queue(parsed, site_total))
    finally:
        restore()


def _queue_crawler(items, nav, cache):
    crawler = ZuJuanCrawler()
    crawler.browser_context = _WatchContext([nav])
    crawler._watch_queue = list(items)
    crawler._watch_progress_cache.update(cache)
    return crawler


def test_over_cap_knowledge_point_expands_into_qtype_slices_in_place():
    """★ 146,010 道的知识点翻页永远采不完 —— 就地展开成 5 个题型分片，
    并且立刻把浏览器带到第一片"""
    nav = _NavPage()
    target = progress.KnowledgeTarget(knowledge_id="zsd5501", title="用勾股定理解三角形")
    crawler = _queue_crawler(
        [WatchTarget("zsd5501", {}, "用勾股定理解三角形"), WatchTarget("zsd9", {}, "别的")],
        nav, {"zsd5501": (target, {})},
    )

    saved = []
    _advance(crawler, "zsd5501", 146010, saved=saved)

    # 原位展开成 5 片，后面那个知识点还排在后面
    assert [i.slice_key for i in crawler._watch_queue] == [
        "t1", "t2", "t3", "t4", "t5", ""
    ]
    assert crawler._watch_queue[-1].knowledge_id == "zsd9"
    assert saved == [("zsd5501", {"scrape_status": "slicing", "site_total": 146010})]
    # 队首变了 -> 自动跳到第一片
    assert nav.goto_urls == ["https://zujuan.xkw.com/czsx/zsd5501/qt1101o2/"]


def test_slice_that_is_still_over_cap_descends_one_more_dimension():
    """某一片还超 9990 -> 再按难度切开，维度顺序和自动模式一致"""
    nav = _NavPage()
    target = progress.KnowledgeTarget(knowledge_id="zsd5501")
    row = progress.SliceProgress(knowledge_id="zsd5501", slice_key="t1")
    crawler = _queue_crawler(
        [WatchTarget("zsd5501", {"qtype": "t1"})], nav, {"zsd5501": (target, {"t1": row})},
    )

    slice_saved = []
    _advance(crawler, "zsd5501", 40000, slice_key="t1", slice_saved=slice_saved)

    assert [i.slice_key for i in crawler._watch_queue] == ["t1d1", "t1d2", "t1d3"]
    assert slice_saved[0][:2] == ("zsd5501", "t1")
    assert slice_saved[0][2]["scrape_status"] == "slicing"
    assert nav.goto_urls == ["https://zujuan.xkw.com/czsx/zsd5501/qt1101d1o2/"]


def test_finished_slice_advances_to_the_next_slice():
    """★ 一片采满 -> 标 done -> 自动切到下一片"""
    nav = _NavPage()
    target = progress.KnowledgeTarget(knowledge_id="zsd5501")
    done_row = progress.SliceProgress(
        knowledge_id="zsd5501", slice_key="t1", site_total=25, covered_pages="1,2,3"
    )
    crawler = _queue_crawler(
        [WatchTarget("zsd5501", {"qtype": "t1"}), WatchTarget("zsd5501", {"qtype": "t2"})],
        nav, {"zsd5501": (target, {"t1": done_row})},
    )

    slice_saved, recounts = [], []
    _advance(crawler, "zsd5501", 25, slice_key="t1", slice_saved=slice_saved, recounts=recounts)

    assert [i.slice_key for i in crawler._watch_queue] == ["t2"]
    assert slice_saved[0][2]["scrape_status"] == "done"
    assert recounts == ["zsd5501/t1"]
    assert nav.goto_urls == ["https://zujuan.xkw.com/czsx/zsd5501/qt1104o2/"]


def test_last_slice_done_rolls_up_to_the_knowledge_point():
    """最后一片采完 -> 汇总回 knowledge_tree"""
    nav = _NavPage()
    target = progress.KnowledgeTarget(knowledge_id="zsd5501", title="甲")
    rows = {
        "t1": progress.SliceProgress("zsd5501", "t1", scrape_status="done"),
        "t2": progress.SliceProgress(
            "zsd5501", "t2", site_total=25, covered_pages="1,2,3"
        ),
    }
    crawler = _queue_crawler([WatchTarget("zsd5501", {"qtype": "t2"})], nav,
                             {"zsd5501": (target, rows)})

    saved, slice_saved = [], []
    _advance(crawler, "zsd5501", 25, slice_key="t2", saved=saved, slice_saved=slice_saved)

    assert crawler._watch_queue == []
    assert saved == [("zsd5501", {"scrape_status": "done"})]
    assert target.scrape_status == progress.STATUS_DONE


def test_capped_slice_makes_the_whole_knowledge_point_capped():
    """★ 四维用尽还超 -> 这一片 capped，整个知识点也标 capped，
    让人知道确实有一部分拿不全，而不是显示'采完了'"""
    nav = _NavPage()
    target = progress.KnowledgeTarget(knowledge_id="zsd5501", title="甲")
    parts = slicing.parse_slice_key("t4d1s1y2020")
    rows = {"t4d1s1y2020": progress.SliceProgress("zsd5501", "t4d1s1y2020")}
    crawler = _queue_crawler([WatchTarget("zsd5501", parts)], nav,
                             {"zsd5501": (target, rows)})

    saved, slice_saved = [], []
    _advance(crawler, "zsd5501", 20000, slice_key="t4d1s1y2020",
             saved=saved, slice_saved=slice_saved)

    assert slice_saved[0][2]["scrape_status"] == "capped"
    assert saved == [("zsd5501", {"scrape_status": "capped"})]


def test_under_cap_and_not_finished_keeps_the_queue_untouched():
    """没超硬顶也没采满 —— 人还在翻，队列不动、不跳转"""
    nav = _NavPage()
    target = progress.KnowledgeTarget(
        knowledge_id="zsd1", site_total=250, covered_pages="1,2"
    )
    crawler = _queue_crawler([WatchTarget("zsd1", {})], nav, {"zsd1": (target, {})})

    saved = []
    _advance(crawler, "zsd1", 250, saved=saved)

    assert [i.slice_key for i in crawler._watch_queue] == [""]
    assert saved == []
    assert nav.goto_urls == []


# ----------------------------- 浅采（广度优先铺底） -----------------------------
#
# ZUJUAN_MAX_PAGES_PER_KNOWLEDGE > 0 时每个知识点只翻前 N 页就走，用来给全部
# 知识点铺一层底、顺带把 site_total 摸出来。
#
# 这一组守的是两个静默数据损坏：
#   ① 只翻了 N 页却标成 done —— 这个知识点后面的题永远不会再被采集，不报错
#   ② 站点只有 3 页的知识点被预算记成 partial —— 永远采不完，同样不报错

@pytest.fixture
def sweep(monkeypatch):
    """把浅采页数预算设成 N"""

    def _set(max_pages):
        monkeypatch.setattr(config, "ZUJUAN_MAX_PAGES_PER_KNOWLEDGE", max_pages, raising=False)

    return _set


def _pages(site_total, count):
    """造 count 页，每页 10 道互不相同的题"""
    return [
        _FakePage(site_total, [f"q{page}_{i}" for i in range(10)])
        for page in range(count)
    ]


def test_sweep_stops_after_budget_and_stays_partial(sweep):
    """站点 500 道 = 50 页，预算 5 页 —— 停在第 5 页，且必须是 partial 不是 done"""
    sweep(5)
    outcome, site_total, saved, requested = _run_page_through(_pages(500, 50))

    assert outcome is slicing.SliceOutcome.INTERRUPTED
    assert outcome.value == "partial"  # 落库的状态值
    assert requested == [1, 2, 3, 4, 5]
    assert len(saved) == 50
    assert site_total == 500


def test_sweep_short_knowledge_point_still_finishes_done(sweep):
    """★ 站点 25 道 = 3 页，预算 5 页 —— 走正常 DONE。

    预算判断放错位置（放在循环顶部而不是"翻到底"判断之后）就会把它记成
    partial，这个知识点会永远挂在待办里采不完。
    """
    sweep(5)
    outcome, site_total, saved, requested = _run_page_through(_pages(25, 3))

    assert outcome is slicing.SliceOutcome.DONE
    assert requested == [1, 2, 3]
    assert site_total == 25


def test_sweep_exact_page_count_prefers_done_over_budget(sweep):
    """站点 50 道 = 5 页，预算也是 5 页 —— 边界上"翻完了"优先于"预算到了"""
    sweep(5)
    outcome, _, _, requested = _run_page_through(_pages(50, 5))

    assert outcome is slicing.SliceOutcome.DONE
    assert requested == [1, 2, 3, 4, 5]


def test_sweep_does_not_slice_over_hard_cap(sweep):
    """超硬顶的知识点浅采时不切片，照样翻够 N 页，站点总数要记下来"""
    sweep(5)
    huge = 146010  # zsd5501 用勾股定理解三角形的真实量级
    outcome, site_total, saved, requested = _run_page_through(_pages(huge, 20))

    assert outcome is not slicing.SliceOutcome.NEED_SLICE
    assert outcome is slicing.SliceOutcome.INTERRUPTED
    assert requested == [1, 2, 3, 4, 5]
    assert len(saved) == 50
    assert site_total == huge  # 摸底的数必须写回去，这是浅采最主要的产出


def test_sweep_resume_counts_from_the_resume_page(sweep):
    """续采：从第 3 页接着浅采 5 页 = 到第 7 页，预算是"本轮翻几页"不是"翻到第几页"""
    sweep(5)
    outcome, _, _, requested = _run_page_through(_pages(500, 50), start_page=3)

    assert outcome is slicing.SliceOutcome.INTERRUPTED
    assert requested == [3, 4, 5, 6, 7]


def test_sweep_zero_total_still_empty(sweep):
    """站点明说没题，浅采一样落 empty（终止状态，不用再排队）"""
    sweep(5)
    outcome, site_total, _, _ = _run_page_through([_FakePage(0, [])])

    assert outcome is slicing.SliceOutcome.EMPTY
    assert site_total == 0


def test_deep_mode_still_slices_over_hard_cap(sweep):
    """回归：预算为 0（正常深采）时，超硬顶还是要转切片"""
    sweep(0)
    outcome, site_total, _, requested = _run_page_through(_pages(146010, 20))

    assert outcome is slicing.SliceOutcome.NEED_SLICE
    assert requested == [1]  # 读到数字的第一时间就转，不傻等翻到第 999 页
    assert site_total == 146010


# --------------------- 浅采：不下钻、不碰已切片的知识点 ---------------------

def _sweep_crawler(outcome, site_total):
    """造一个 _page_through 返回指定结果的爬虫，记录它有没有去下钻"""
    crawler = ZuJuanCrawler()
    calls = {"descend": 0, "written": []}

    async def fake_page_through(target, parts, slices, start_page):
        return outcome, site_total

    async def fake_descend(target, parts, slices, total):
        calls["descend"] += 1
        return "slicing"

    async def fake_write(target, parts, slices, **fields):
        calls["written"].append(fields)

    crawler._page_through = fake_page_through
    crawler._descend = fake_descend
    crawler._write_progress = fake_write
    return crawler, calls


def test_sweep_need_slice_is_written_as_partial_without_descending(sweep):
    """翻页中途才发现超硬顶：浅采记 partial，绝不下钻建分片"""
    sweep(5)
    crawler, calls = _sweep_crawler(slicing.SliceOutcome.NEED_SLICE, 146010)
    target = progress.KnowledgeTarget(knowledge_id="zsd5501", title="用勾股定理解三角形")

    status = asyncio.run(crawler._crawl_slice(target, {}, {}))

    assert calls["descend"] == 0
    assert status == "partial"
    assert calls["written"] == [{"scrape_status": "partial", "site_total": 146010}]


def test_deep_mode_need_slice_still_descends(sweep):
    """回归：正常深采时 NEED_SLICE 照旧下钻"""
    sweep(0)
    crawler, calls = _sweep_crawler(slicing.SliceOutcome.NEED_SLICE, 146010)
    target = progress.KnowledgeTarget(knowledge_id="zsd5501", title="用勾股定理解三角形")

    status = asyncio.run(crawler._crawl_slice(target, {}, {}))

    assert calls["descend"] == 1
    assert status == "slicing"


def test_sweep_skips_knowledge_points_already_slicing(sweep):
    """已经在切片采的知识点手里的题远不止这几页，浅采跳过、不下钻"""
    sweep(5)
    crawler, calls = _sweep_crawler(slicing.SliceOutcome.DONE, 100)
    target = progress.KnowledgeTarget(
        knowledge_id="zsd5501", title="用勾股定理解三角形",
        scrape_status=progress.STATUS_SLICING,
    )

    status = asyncio.run(crawler._crawl_slice(target, {}, {}))

    assert status == progress.STATUS_SLICING
    assert calls["descend"] == 0
    assert calls["written"] == []


# --------------------- 浅采：待办清单的筛选下推到 SQL ---------------------

def _captured_targets_sql(monkeypatch, **kwargs):
    """跑一次 fetch_leaf_targets，把它发出去的 SELECT 抓回来"""
    captured = {}

    class _Session:
        async def execute(self, stmt):
            captured["sql"] = str(stmt.compile(compile_kwargs={"literal_binds": True}))

            class _Result:
                def all(self_inner):
                    return []

            return _Result()

    class _Ctx:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(progress, "get_session", lambda: _Ctx())
    asyncio.run(progress.fetch_leaf_targets(**kwargs))
    return captured["sql"]


def test_only_uncrawled_narrows_to_status_none(monkeypatch):
    sql = _captured_targets_sql(monkeypatch, only_uncrawled=True)
    where = sql.split("ORDER BY")[0]
    assert "scrape_status = 'none'" in where
    # partial/slicing 不能混进来 —— 浅采只铺没跑过的底。
    # 注意只能看 WHERE：ORDER BY 的优先级 CASE 里本来就写着这两个状态名
    assert "'partial'" not in where and "'slicing'" not in where


def test_default_still_picks_up_partial_and_slicing(monkeypatch):
    """回归：不开 only_uncrawled 时待办口径不变"""
    sql = _captured_targets_sql(monkeypatch)
    where = sql.split("ORDER BY")[0]
    assert "'none'" in where and "'partial'" in where and "'slicing'" in where


def test_exclude_paths_is_pushed_down_to_sql(monkeypatch):
    """★ 排除条件必须下推到 SQL：先 limit 后在 Python 里筛会让 limit 少给行"""
    sql = _captured_targets_sql(
        monkeypatch, exclude_path_keywords=["五四制小学衔接", "数学竞赛"], limit=50
    )
    where = sql.split("ORDER BY")[0]
    assert "NOT LIKE '%五四制小学衔接%'" in where
    assert "NOT LIKE '%数学竞赛%'" in where
    assert "path IS NULL" in where  # path 为空的节点不该被顺手滤掉
    assert "LIMIT 50" in sql.split("ORDER BY")[1]


def test_blank_exclude_keywords_are_ignored(monkeypatch):
    sql = _captured_targets_sql(monkeypatch, exclude_path_keywords=["", "  ", None])
    assert "NOT LIKE" not in sql
