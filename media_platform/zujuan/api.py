# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zujuan/api.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网列表页背后的 XHR 接口。

站点自己的分页器点下去打的就是这个接口，返回的 ``data.html`` 是一段只含
``div.tk-quest-item`` 的片段 —— 和整页渲染出来的卡片结构逐字节一致，
``ZuJuanExtractor`` 直接就能解析（tests/test_zujuan_api.py 用线上真实响应锁住了）。

用它替代"渲染整页 + 点分页器"能省掉渲染和绝大部分流量（实测 9.1 KB / 页），
但有一个**必须补上的缺口**：

    ★ ``#questioncount``（"共计 N 道试题"）和 ``div.tk-pager`` 都是页面外壳，
      不在这段片段里。``extract_site_total()`` 对它一律返回 None，而 None 在
      ``_page_through()`` 里的含义是"这一趟没读到题数，保留 partial 下次重试"
      —— 照搬会导致每个知识点都在第 1 页中断，一道题也采不到。
      题数要改从接口的 ``data.total`` 取。

本模块只做纯函数（拼参数、解响应），不碰网络也不碰数据库，和 slicing.py 一样。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import slicing

# 接口路径，拼在 ZUJUAN_HOST 后面
API_PATH = "/zujuan-api/question/list"

# 页码参数名。站点用 curPage
PAGE_FIELD = "curPage"

# ★ 照抄浏览器真实请求里的固定参数，一个都不能少。
#   这些字段看着都是"默认值"，但服务端很可能按"有没有传"走不同分支，
#   少传一个的表现不是报错而是**筛选条件被忽略**，返回整个知识点的题 ——
#   那会把 A 分片的题当成 B 分片入库，属于不报错的静默数据损坏
FIXED_FIELDS: Dict[str, str] = {
    "pageName": "zsd",
    "courseId": "0",
    "canTreeMultiple": "false",
    "canCategoryId": "false",
    "categoryIds[0]": "0",
    "difficultyMin": "-1",
    "difficultyMax": "-1",
    "paperTypeId": "0",
    "tagId": "0",
    "provinceId": "-1",
    "learngrade": "0",
    "term": "0",
    "quesAttributeId": "0",
    "examMethodId": "0",
    "isFresh": "0",
    "catelogTokpointId": "0",
}

# 三个筛选维度在接口里的字段名。维度值本身复用 slicing 的码表，
# 不在这里另抄一份 —— 抄一份就会有两份真相，改了一处忘了另一处
QTYPE_FIELD = "quesType"
DIFFICULTY_FIELD = "quesDiff"
YEAR_FIELD = "quesYear"

# 没有这一维时传的"不限"值
UNLIMITED = "0"


@dataclass(frozen=True)
class ApiListPage:
    """接口返回的一页：卡片 HTML 片段 + 站点报的总题数"""

    html: str
    total: int


def category_id(knowledge_id: str) -> str:
    """zsd5043 -> 5043。就是 knowledge_tree.node_id 那一列的值"""
    text = (knowledge_id or "").strip()
    return text[3:] if text.lower().startswith("zsd") else text


def qtype_value(parts: Dict[str, str]) -> str:
    """题型 + 子题型拼成接口要的那个码。

    和 ``slicing.url_filter_segment()`` 用的是同一张码表、同一个拼法：
    子题型是**粘在题型码后面的两位**（1103 + 05 = 110305），脱离题型无法单独
    表达。这里的取值直接来自 SliceValue，改码表两边一起变。
    """
    qtype_code = parts.get(slicing.DIM_QTYPE)
    sub_code = parts.get(slicing.DIM_SUB_TYPE)
    if sub_code and not qtype_code:
        raise ValueError("子题型必须依附于题型，不能单独出现在接口参数里")
    if not qtype_code:
        return UNLIMITED
    value = slicing.slice_value(slicing.DIM_QTYPE, qtype_code).db_value
    if sub_code:
        value += slicing.slice_value(slicing.DIM_SUB_TYPE, sub_code).url_code
    return value


def difficulty_value(parts: Dict[str, str]) -> str:
    """d1/d2/d3 -> 1/2/3。URL 段码去掉开头的 d 就是接口值"""
    code = parts.get(slicing.DIM_DIFFICULTY)
    if not code:
        return UNLIMITED
    return slicing.slice_value(slicing.DIM_DIFFICULTY, code).url_code.lstrip("d")


def year_value(parts: Dict[str, str]) -> str:
    """y2023 -> 2023，y-1（更早以前）-> -1"""
    code = parts.get(slicing.DIM_YEAR)
    if not code:
        return UNLIMITED
    return slicing.slice_value(slicing.DIM_YEAR, code).db_value


def build_payload(
    knowledge_id: str,
    parts: Optional[Dict[str, str]] = None,
    page: int = 1,
    *,
    bank_id: str = "2",
    order_by: str = "2",
    page_base: int = 1,
) -> Dict[str, str]:
    """拼一次列表请求的 form data。

    ``page`` 一律是**人看的页码**（第 1 页就是 1），``page_base`` 决定接口那边
    从几开始数：``page_base=1`` 直接传，``page_base=0`` 传 page-1。

    站点是 1 基（2026-09 实测）。线上抓到的那次 ``curPage=67`` 配 Referer ``o2p68``
    看着像 0 基，实际是人停在第 68 页点了"67"那个页码 —— curPage 是**要去的那一页**，
    Referer 只是从哪儿来的。这条记录很容易看反，所以在这里写清楚。

    ★ 页码基数错了是不报错的静默数据损坏 —— 每一页的内容都错位一页，进度却照记。
      ``core._api_aligned()`` 每片开工前会拿浏览器那一页的题目 ID 再对一次。
    """
    parts = parts or {}
    payload = dict(FIXED_FIELDS)
    payload["bankId"] = str(bank_id)
    payload["categoryId"] = category_id(knowledge_id)
    payload[QTYPE_FIELD] = qtype_value(parts)
    payload[DIFFICULTY_FIELD] = difficulty_value(parts)
    payload[YEAR_FIELD] = year_value(parts)
    payload["orderBy"] = str(order_by)
    payload[PAGE_FIELD] = str(max(0, int(page) - (1 - int(page_base))))
    return payload


def parse_response(body: str) -> Optional[ApiListPage]:
    """把接口返回解析成 (html, total)，认不出一律返回 None。

    ★ 认不出必须返回 None 而不是当成空页：被 WAF 拦下时这里拿到的是一段 HTML
      而不是 JSON，判成"这一页没题"会把知识点标成采完。None 的含义在上层是
      "这一趟没读到，保留 partial 下次重试"，和读不到 #questioncount 一致。
    """
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("code", "")).strip() != "0":
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    raw_total = data.get("total")
    if isinstance(raw_total, bool):  # bool 是 int 的子类，先挡掉
        return None
    if isinstance(raw_total, int):
        total = raw_total
    elif isinstance(raw_total, str) and raw_total.strip().lstrip("-").isdigit():
        total = int(raw_total)
    else:
        return None
    if total < 0:
        return None

    html = data.get("html")
    if html is None:
        html = ""
    if not isinstance(html, str):
        return None
    return ApiListPage(html=html, total=total)


def question_ids(page_html: str) -> List[str]:
    """这一页的题目 ID 列表，按出现顺序。对齐校验和硬顶检测都用它"""
    from .help import QUESTION_ID_RE

    return QUESTION_ID_RE.findall(page_html or "")
