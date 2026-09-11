# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_zujuan_api.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""组卷网列表接口（api 取页模式）"""

import asyncio
import json
import pathlib

import pytest

import config
from media_platform.zujuan import api, slicing
from media_platform.zujuan.core import ZuJuanCrawler
from media_platform.zujuan.help import ZuJuanExtractor
from store.zujuan import _progress as progress

TEST_DATA = pathlib.Path(__file__).resolve().parents[1] / "media_platform" / "zujuan" / "test_data"
REAL_RESPONSE = (TEST_DATA / "zujuan_api_list.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 参数拼装
# ---------------------------------------------------------------------------

def test_category_id_strips_the_zsd_prefix():
    """接口要的是不带前缀的数字，就是 knowledge_tree.node_id 那一列"""
    assert api.category_id("zsd5043") == "5043"
    assert api.category_id("5043") == "5043"


def test_payload_without_filters_asks_for_everything():
    payload = api.build_payload("zsd5043", {}, page=67)
    assert payload["categoryId"] == "5043"
    assert payload[api.PAGE_FIELD] == "67"
    assert payload[api.QTYPE_FIELD] == api.UNLIMITED
    assert payload[api.DIFFICULTY_FIELD] == api.UNLIMITED
    assert payload[api.YEAR_FIELD] == api.UNLIMITED
    # 固定字段一个都不能少 —— 少传一个的表现不是报错而是筛选条件被忽略
    for field, value in api.FIXED_FIELDS.items():
        assert payload[field] == value


def test_payload_maps_every_slice_dimension():
    """t4d1s5y2023 = 解答题·容易·问答题·2023 年"""
    parts = {
        slicing.DIM_QTYPE: "t4",
        slicing.DIM_DIFFICULTY: "d1",
        slicing.DIM_SUB_TYPE: "s5",
        slicing.DIM_YEAR: "y2023",
    }
    payload = api.build_payload("zsd5841", parts, page=3)
    # ★ 子题型是粘在题型码后面的两位，和 URL 里 qt110305 的拼法完全一致
    assert payload[api.QTYPE_FIELD] == "110305"
    assert payload[api.DIFFICULTY_FIELD] == "1"
    assert payload[api.YEAR_FIELD] == "2023"


def test_payload_qtype_matches_the_url_segment():
    """接口码和 URL 段码必须出自同一张表，不能各抄一份"""
    for code in ("t1", "t2", "t3", "t4", "t5"):
        parts = {slicing.DIM_QTYPE: code}
        assert api.build_payload("zsd1", parts)[api.QTYPE_FIELD] == (
            slicing.url_filter_segment(parts).removeprefix("qt")
        )


def test_payload_earlier_than_year_is_minus_one():
    parts = {slicing.DIM_YEAR: "y-1"}
    assert api.build_payload("zsd1", parts)[api.YEAR_FIELD] == "-1"


def test_sub_type_without_qtype_is_rejected():
    """子题型脱离题型无法表达，和 url_filter_segment 一样要拒绝而不是猜"""
    with pytest.raises(ValueError):
        api.build_payload("zsd1", {slicing.DIM_SUB_TYPE: "s1"})


def test_default_page_base_is_one():
    """★ 站点是 1 基（2026-09 实测）。线上抓到的 curPage=67 配 Referer o2p68
    看着像 0 基，实际是人停在第 68 页点了"67"那个页码 —— curPage 是要去的那一页。
    这条记录很容易看反，所以把结论锁在这里"""
    assert config.ZUJUAN_API_PAGE_BASE == 1
    assert api.build_payload("zsd5043", {}, page=67)[api.PAGE_FIELD] == "67"


def test_page_base_zero_shifts_the_page_number():
    """★ curPage 从 0 还是 1 数错了不会报错，只会让每页整体错位一页"""
    assert api.build_payload("zsd1", {}, page=68, page_base=1)[api.PAGE_FIELD] == "68"
    assert api.build_payload("zsd1", {}, page=68, page_base=0)[api.PAGE_FIELD] == "67"
    # 第 1 页在 0 基下是 0，不能变成 -1
    assert api.build_payload("zsd1", {}, page=1, page_base=0)[api.PAGE_FIELD] == "0"


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------

def test_parses_the_real_response():
    result = api.parse_response(REAL_RESPONSE)
    assert result is not None
    assert result.total == 677
    assert "tk-quest-item" in result.html


def test_real_response_parses_into_the_same_fields_as_a_full_page():
    """★ 接口返回的 data.html 和整页渲染出来的卡片结构一致，
    ZuJuanExtractor 不用改一行就能解析"""
    result = api.parse_response(REAL_RESPONSE)
    questions = ZuJuanExtractor().extract_questions(
        result.html, list_url="https://zujuan.xkw.com/czsx/zsd5043/o2p68/", page=68
    )
    assert len(questions) == 2
    first = questions[0]
    assert first.question_id == "9169058"
    assert first.qtype_full == "解答题-问答题"
    assert first.qtype_sub == "问答题"
    assert first.difficulty_band == "适中"
    assert first.province_code == "320000"
    assert first.used_count == 390
    assert [k.id for k in first.knowledge] == ["zsd6033", "zsd5043"]
    assert len(first.sources) == 3
    assert first.stem_html.startswith("我们知道")  # 开头的 "1 . " 已剥掉
    assert questions[1].is_famous_school == 1


def test_site_total_is_only_available_from_the_envelope():
    """★ 这是 api 模式唯一必须补的缺口：#questioncount 和 tk-pager 都是页面外壳，
    不在片段里。extract_site_total() 返回 None，而 None 在 _page_through 里
    的含义是"没读到，保留 partial 下次重试" —— 照搬会导致一道题也采不到"""
    result = api.parse_response(REAL_RESPONSE)
    assert ZuJuanExtractor().extract_site_total(result.html) is None
    assert result.total == 677


def test_html_instead_of_json_is_not_an_empty_page():
    """被 WAF 拦下时拿到的是 HTML。必须返回 None（没读到），
    不能当成"这一页没题"—— 那会把知识点标成采完"""
    assert api.parse_response("<html><body>滑动验证</body></html>") is None
    assert api.parse_response("") is None


def test_non_zero_code_is_rejected():
    assert api.parse_response(json.dumps({"code": "500", "data": {"html": "", "total": 1}})) is None


def test_missing_or_bogus_total_is_rejected():
    assert api.parse_response(json.dumps({"code": "0", "data": {"html": "x"}})) is None
    assert api.parse_response(json.dumps({"code": "0", "data": {"html": "x", "total": True}})) is None
    assert api.parse_response(json.dumps({"code": "0", "data": {"html": "x", "total": -3}})) is None
    # 数字串是可以的，站点这类字段经常字符串化
    ok = api.parse_response(json.dumps({"code": "0", "data": {"html": "x", "total": "42"}}))
    assert ok is not None and ok.total == 42


def test_empty_html_with_a_total_is_a_valid_answer():
    """翻过最后一页时接口会返回空 html —— 这是合法结果，
    该由上层拿 total 算出的页数去判，不在这里当成失败"""
    result = api.parse_response(json.dumps({"code": "0", "data": {"html": "", "total": 677}}))
    assert result is not None
    assert result.html == "" and result.total == 677


def test_question_ids_reads_in_document_order():
    result = api.parse_response(REAL_RESPONSE)
    assert api.question_ids(result.html) == ["9169058", "3170291"]


# ---------------------------------------------------------------------------
# 取页分流与对齐校验
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, api_pages=None):
        self.browser_calls = []
        self.api_calls = []
        self._api_pages = api_pages or {}

    async def get_page_html(self, url, referer="", page_no=None, base_url=""):
        self.browser_calls.append(page_no)
        return f"browser:{page_no}"

    async def fetch_list_api(self, knowledge_id, parts, page, referer, bank_id="2"):
        self.api_calls.append(page)
        return self._api_pages.get(page)


class _FakeExtractor:
    def extract_site_total(self, page_html):
        return 500

    def extract_page_url_template(self, page_html):
        return None


def _crawler(api_pages=None, verified=True):
    crawler = ZuJuanCrawler()
    crawler.zujuan_client = _FakeClient(api_pages)
    crawler._extractor = _FakeExtractor()
    if verified:
        crawler._api_verified.add("")
    return crawler


def _fetch(crawler, page, first_page=1):
    target = progress.KnowledgeTarget(knowledge_id="zsd5043", title="测试")
    return asyncio.run(
        crawler._fetch_list_page(
            target, {}, page, first_page,
            "https://zujuan.xkw.com/czsx/zsd5043/o2p%d/" % page,
            "https://zujuan.xkw.com/czsx/zsd5043/o2/",
        )
    )


@pytest.fixture
def api_mode(monkeypatch):
    monkeypatch.setattr(config, "ZUJUAN_FETCH_MODE", "api", raising=False)


def test_first_page_still_goes_through_the_browser(api_mode):
    """★ 每片首页仍走浏览器：那一趟要过 WAF 挑战、刷 Cookie、读防伪令牌、
    读"共计 N 道试题"，这些接口都给不了"""
    crawler = _crawler()
    html, total = _fetch(crawler, page=1)
    assert html == "browser:1"
    assert total == 500
    assert crawler.zujuan_client.api_calls == []


def test_later_pages_go_through_the_api(api_mode):
    crawler = _crawler({2: api.ApiListPage(html="<i>2</i>", total=677)})
    html, total = _fetch(crawler, page=2)
    assert (html, total) == ("<i>2</i>", 677)
    assert crawler.zujuan_client.browser_calls == []


def test_api_failure_falls_back_to_the_browser(api_mode):
    """接口没给出能认的结果时退回浏览器重取，
    绝不能把"没读到"当成"这一页没题"往下走"""
    crawler = _crawler({2: None})
    html, total = _fetch(crawler, page=2)
    assert html == "browser:2"
    assert total == 500


def test_browser_mode_never_touches_the_api():
    crawler = _crawler({2: api.ApiListPage(html="x", total=1)})
    html, _ = _fetch(crawler, page=2)
    assert html == "browser:2"
    assert crawler.zujuan_client.api_calls == []


def test_alignment_check_passes_when_ids_match(api_mode):
    same = '<div questionid="1"></div><div questionid="2"></div>'
    crawler = _crawler({1: api.ApiListPage(html=same, total=500)}, verified=False)
    crawler._api_probe[""] = (1, ["1", "2"], 500)
    assert asyncio.run(crawler._api_aligned(
        progress.KnowledgeTarget(knowledge_id="zsd5043", title="t"), {}, "", "zsd5043", "u"
    ))
    assert crawler._api_enabled is True


def test_alignment_check_disables_the_api_when_ids_differ(api_mode):
    """★ 页码基数或参数映射错了就是这个现象：接口能正常返回，只是返回的不是这一页。
    这时候必须整轮关掉接口退回浏览器 —— 慢，但不会把 A 页的题记成 B 页"""
    other = '<div questionid="7"></div><div questionid="8"></div>'
    crawler = _crawler({1: api.ApiListPage(html=other, total=500)}, verified=False)
    crawler._api_probe[""] = (1, ["1", "2"], 500)
    assert not asyncio.run(crawler._api_aligned(
        progress.KnowledgeTarget(knowledge_id="zsd5043", title="t"), {}, "", "zsd5043", "u"
    ))
    assert crawler._api_enabled is False


def test_alignment_check_disables_the_api_when_total_differs(api_mode):
    """筛选参数被忽略的典型现象：题目对得上但总数是整个知识点的"""
    same = '<div questionid="1"></div>'
    crawler = _crawler({1: api.ApiListPage(html=same, total=99999)}, verified=False)
    crawler._api_probe[""] = (1, ["1"], 500)
    assert not asyncio.run(crawler._api_aligned(
        progress.KnowledgeTarget(knowledge_id="zsd5043", title="t"), {}, "", "zsd5043", "u"
    ))
    assert crawler._api_enabled is False


def test_without_a_probe_page_the_api_is_not_used(api_mode):
    """没有可比的权威页就不敢用接口"""
    crawler = _crawler(verified=False)
    assert not asyncio.run(crawler._api_aligned(
        progress.KnowledgeTarget(knowledge_id="zsd5043", title="t"), {}, "", "zsd5043", "u"
    ))


def test_probe_is_recorded_from_the_browser_page(api_mode):
    """浏览器取到的首页要被记下来，供这一片第一次用接口时做对齐校验"""

    async def page_with_ids(url, referer="", page_no=None, base_url=""):
        return '<div questionid="11"></div><div questionid="22"></div>'

    crawler = _crawler(verified=False)
    crawler.zujuan_client.get_page_html = page_with_ids
    _fetch(crawler, page=1)
    assert crawler._api_probe[""] == (1, ["11", "22"], 500)


# ---------------------------------------------------------------------------
# 参数体检
# ---------------------------------------------------------------------------

def test_page_size_other_than_the_stored_one_is_rejected(monkeypatch):
    """★ 实测站点忽略 pageSize=50，这个开关本来就没用途；留着是为了守住
    covered_pages —— 几十万条页码都是按 10 条一页记的，页大小一变这些进度
    全部失去意义，断点续采会静默跳页"""
    monkeypatch.setattr(config, "ZUJUAN_API_PAGE_SIZE", 50, raising=False)
    with pytest.raises(ValueError, match="ZUJUAN_API_PAGE_SIZE"):
        ZuJuanCrawler._check_api_config()


def test_page_size_zero_and_ten_are_fine(monkeypatch):
    for value in (0, slicing.PAGE_SIZE):
        monkeypatch.setattr(config, "ZUJUAN_API_PAGE_SIZE", value, raising=False)
        ZuJuanCrawler._check_api_config()


def test_bogus_page_base_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "ZUJUAN_API_PAGE_SIZE", 0, raising=False)
    monkeypatch.setattr(config, "ZUJUAN_API_PAGE_BASE", 2, raising=False)
    with pytest.raises(ValueError, match="ZUJUAN_API_PAGE_BASE"):
        ZuJuanCrawler._check_api_config()
