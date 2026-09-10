# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/model/m_zujuan.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网题目数据模型

★ 所有可选字段一律 Optional[...] = None，不用 "" / 0 当默认值：
入库时"值为空的列直接不写"，让数据库保留已有值。如果默认值是空串或 0，
代码就没法区分"这次没解析到"和"解析出来就是空"，会把上一轮写好的数据冲掉。
得分率 0 更是合法取值，拿它当占位符会直接产生错数据。
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class ZujuanKnowledge(BaseModel):
    """知识点标签，一题可挂多个"""

    id: str = Field(default="", description="知识点ID，如 zsd4713")
    name: str = Field(default="", description="知识点名称")


class ZujuanSource(BaseModel):
    """来源试卷，一题可被多套试卷收录"""

    paper_id: str = Field(default="", description="试卷ID")
    bank_id: str = Field(default="", description="题库编号")
    title: str = Field(default="", description="试卷全名")
    url: str = Field(default="", description="试卷相对链接，如 /2p3391141.html")


class ZujuanFormula(BaseModel):
    """题干里的公式图（URL 路径含 /Upload/formula/）"""

    url: str = Field(default="", description="公式图URL")
    img_key: str = Field(default="", description="去掉查询参数和扩展名的文件名，站点算好的内容哈希")
    latex: Optional[str] = Field(default=None, description="LaTeX 源码，绝大多数情况读不到")
    latex_from: Optional[str] = Field(default=None, description="latex 是从哪个属性读到的")


class ZujuanImage(BaseModel):
    """题干里的插图（非公式图）"""

    url: str = Field(default="", description="插图URL")


class ZujuanQuestion(BaseModel):
    """一道题的完整解析结果"""

    # ---- 卡片直读 ----
    question_id: Optional[str] = Field(default=None, description="题目ID，卡片 questionid 属性")
    bank_id: Optional[str] = Field(default=None, description="题库编号，初中数学=2")

    # ---- 题干 ----
    stem_html: Optional[str] = Field(default=None, description="题干HTML，exam-item__cnt 的 innerHTML，已剥位置号")
    stem_status: Optional[str] = Field(default=None, description="题干进度：html_saved / none")
    stem_hash: Optional[str] = Field(default=None, description="stem_html 的 md5，重复抓取判重用")
    card_html: Optional[str] = Field(default=None, description="整张卡片原文，只进JSONL，供以后离线重解析")

    # ---- 题型 ----
    qtype: Optional[str] = Field(default=None, description="题型大类，按钮 qyname")
    qtype_code: Optional[str] = Field(default=None, description="题型码，按钮 qyid")
    qtype_full: Optional[str] = Field(default=None, description="完整题型，如 解答题-计算题，只在正文 info-cnt 里")
    qtype_sub: Optional[str] = Field(default=None, description="题型子类型，由 qtype_full 拆出")

    # ---- 难度 ----
    difficulty: Optional[str] = Field(default=None, description="5档难度名，按钮 qdname")
    difficulty_code: Optional[str] = Field(default=None, description="5档难度码，按钮 qdid")
    difficulty_band: Optional[str] = Field(default=None, description="3档难度，由 score_rate 重算，与5档不可混用")
    score_rate: Optional[float] = Field(default=None, description="得分率，按钮 qdvalue")

    # ---- 来源与归属 ----
    source: Optional[str] = Field(default=None, description="来源试卷全名，按钮 questitle")
    title_abbr: Optional[str] = Field(default=None, description="三段式简称原串，按钮 titleabbreviation")
    category_id: Optional[str] = Field(default=None, description="所属章节ID")
    category_name: Optional[str] = Field(default=None, description="所属章节名")

    # ---- title_abbr 拆出来的 8 个字段 ----
    school_year: Optional[str] = Field(default=None, description="学年，如 2025-2026")
    year: Optional[int] = Field(default=None, description="年份，取学年起始年，取不到从来源标题兜底")
    grade_level: Optional[str] = Field(default=None, description="年级，如 七年级")
    term: Optional[str] = Field(default=None, description="学期：上学期/下学期")
    province: Optional[str] = Field(default=None, description="省份")
    province_code: Optional[str] = Field(default=None, description="省级行政区划码 GB/T 2260")
    city: Optional[str] = Field(default=None, description="地级市，直辖市留空")
    source_type: Optional[str] = Field(default=None, description="来源类型，如 期中/中考真题")

    # ---- 其余标量 ----
    paper_id: Optional[str] = Field(default=None, description="主来源试卷ID，即 sources[0]")
    used_count: Optional[int] = Field(default=None, description="被组卷引用次数")
    is_famous_school: Optional[int] = Field(default=None, description="名校角标：1/0，没有就是明确的0")
    is_real_exam: Optional[int] = Field(default=None, description="真题角标：1/0，与 source_type=中考真题 是两回事")
    updated_hint: Optional[str] = Field(default=None, description="更新时间文案，只进JSONL")
    detail_url: Optional[str] = Field(default=None, description="详情页相对链接，只进JSONL")
    sub_question_count: Optional[str] = Field(default=None, description="小问数，按钮 childnum，★只进JSONL不入库")

    knowledge_id: Optional[str] = Field(default=None, description="主知识点ID，即 knowledge[0].id")
    knowledge_tags: Optional[str] = Field(default=None, description="全部知识点名称的JSON数组字符串")

    # ---- 多值 ----
    knowledge: List[ZujuanKnowledge] = Field(default_factory=list, description="全部知识点")
    sources: List[ZujuanSource] = Field(default_factory=list, description="全部来源试卷")
    formulas: List[ZujuanFormula] = Field(default_factory=list, description="题干里的公式图")
    images: List[ZujuanImage] = Field(default_factory=list, description="题干里的插图")
    tags: List[str] = Field(default_factory=list, description="卡片角标文字，如 名校/真题")

    # ---- 抓取上下文，写入时补齐 ----
    grade: Optional[str] = Field(default=None, description="学段固定值：middle=初中 / high=高中")
    list_url: Optional[str] = Field(default=None, description="这道题是在哪个列表页抓到的")
    raw_day: Optional[str] = Field(default=None, description="原始JSONL落在哪一天的文件，YYYY-MM-DD")
    captured_at: Optional[str] = Field(default=None, description="抓取时刻，只进JSONL")
    page: int = Field(default=0, description="所在列表页页码，仅日志用，不入库不进JSONL")
