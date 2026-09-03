# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zujuan/exception.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

from httpx import RequestError


class DataFetchError(RequestError):
    """something error when fetch"""


class ChallengePageError(Exception):
    """页面返回的是 CDN 反爬 JS 挑战页，需要用浏览器重新取一次"""


class CaptchaPageError(Exception):
    """页面返回的是人机验证（滑块/点选），httpx 无解，必须由浏览器里的人来过"""


class RateLimitError(DataFetchError):
    """被 WAF 限流（HTTP 429），应当退避后重试而不是立刻放弃"""


class UnsupportedCrawlerType(Exception):
    """组卷网不支持该爬取类型"""
