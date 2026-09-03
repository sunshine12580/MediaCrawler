# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/test/test_utils.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#



# -*- coding: utf-8 -*-

from unittest.mock import AsyncMock

import pytest

from tools import utils


def test_convert_cookies():
    xhs_cookies = "a1=x000101360; webId=1190c4d3cxxxx125xxx; "
    cookie_dict = utils.convert_str_cookie_to_dict(xhs_cookies)
    assert cookie_dict.get("webId") == "1190c4d3cxxxx125xxx"
    assert cookie_dict.get("a1") == "x000101360"


@pytest.mark.asyncio
async def test_convert_browser_context_cookies_uses_url_filter():
    browser_context = AsyncMock()
    browser_context.cookies.return_value = [{"name": "sessionid", "value": "abc"}]

    cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
        browser_context,
        urls=["https://www.douyin.com"],
    )

    browser_context.cookies.assert_awaited_once_with(urls=["https://www.douyin.com"])
    assert cookie_str == "sessionid=abc"
    assert cookie_dict == {"sessionid": "abc"}


def test_rfc2822_to_timestamp_converts_utc_offset():
    # 2023-12-23 17:12:54 +0800 == 2023-12-23 09:12:54 UTC == 1703322774
    assert utils.rfc2822_to_timestamp("Sat Dec 23 17:12:54 +0800 2023") == 1703322774


def test_rfc2822_to_timestamp_agrees_with_china_datetime():
    rfc2822_time = "Sat Dec 23 17:12:54 +0800 2023"

    assert utils.rfc2822_to_timestamp(rfc2822_time) == int(
        utils.rfc2822_to_china_datetime(rfc2822_time).timestamp()
    )
