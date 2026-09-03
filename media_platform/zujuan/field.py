# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zujuan/field.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

from enum import Enum


class QuestionSortType(Enum):
    """列表页 URL 中的排序段（o1/o2/o3...），仅用于拼 URL 时参考"""

    DEFAULT = "o1"
    LATEST = "o2"
    MOST_USED = "o3"
