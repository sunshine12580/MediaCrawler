# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/model/m_zujuan.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

from pydantic import BaseModel, Field


class ZujuanQuestion(BaseModel):
    """组卷网题目数据模型（仅公开信息，题库题目本身不含用户个人信息）"""

    question_id: str = Field(default="", description="题目ID")
    bank_id: str = Field(default="", description="题库ID，11=高中数学等")
    question_type: str = Field(default="", description="题型，如 单选题/填空题/解答题")
    difficulty_name: str = Field(default="", description="难度名称，如 容易/较易/中等")
    difficulty_value: str = Field(default="", description="难度系数，如 0.95")
    category_id: str = Field(default="", description="知识点ID")
    category_name: str = Field(default="", description="知识点名称")
    knowledge_points: str = Field(default="", description="全部知识点，英文逗号分隔")
    title: str = Field(default="", description="题目所属试卷/来源标题")
    content_html: str = Field(default="", description="题干原始HTML（含公式图片、选项表格）")
    content_text: str = Field(default="", description="题干纯文本")
    option_list: str = Field(default="", description="选项列表，JSON 字符串")
    image_list: str = Field(default="", description="题干中的公式/插图URL，英文逗号分隔")
    answer: str = Field(default="", description="答案，未登录时为空")
    analysis: str = Field(default="", description="解析，未登录时为空")
    source_name: str = Field(default="", description="题目出处，如 26-27高一上·全国·课后作业")
    source_url: str = Field(default="", description="出处试卷链接")
    used_count: str = Field(default="", description="组卷次数，如 9次组卷")
    update_label: str = Field(default="", description="更新时间标签，如 今日")
    detail_url: str = Field(default="", description="题目详情页链接")
    list_url: str = Field(default="", description="来源列表页URL")
    page: int = Field(default=0, description="所在列表页页码")
    add_ts: int = Field(default=0, description="记录添加时间戳")
    last_modify_ts: int = Field(default=0, description="记录最后修改时间戳")
