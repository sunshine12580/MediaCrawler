# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/playwright_sign.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

# Xiaohongshu signature generation using xhshow pure-algorithm library
#
# 致谢：本签名实现依赖 xhshow 开源库, 由 Cloxl 提供
# 仓库地址: https://github.com/Cloxl/xhshow
# 许可协议: MIT License
#
# 依赖 xhshow>=0.2.0: 该版本原生修复了 GET 请求 a3_hash 计算的 bug
# (https://github.com/Cloxl/xhshow/issues/104), 不再需要在本地打 monkey-patch。

from typing import Any, Dict, Optional, Union

from .xhs_sign import get_trace_id


def sign_with_xhshow(
    uri: str,
    data: Optional[Union[Dict, str]] = None,
    cookie_str: str = "",
    method: str = "POST",
) -> Dict[str, Any]:
    """
    使用 xhshow 纯算法生成完整签名请求头

    Args:
        uri: API path
        data: Request data (GET params dict or POST payload dict)
        cookie_str: Cookie string
        method: Request method (GET or POST)

    Returns:
        Dictionary containing x-s, x-t, x-s-common, x-b3-traceid
    """
    from xhshow import Xhshow
    xhshow_client = Xhshow()

    if method.upper() == "POST":
        headers = xhshow_client.sign_headers_post(
            uri=uri,
            cookies=cookie_str,
            payload=data if isinstance(data, dict) else {},
        )
    else:
        headers = xhshow_client.sign_headers_get(
            uri=uri,
            cookies=cookie_str,
            params=data if isinstance(data, dict) else {},
        )

    return {
        "x-s": headers.get("x-s", ""),
        "x-t": headers.get("x-t", ""),
        "x-s-common": headers.get("x-s-common", ""),
        "x-b3-traceid": headers.get("x-b3-traceid", get_trace_id()),
    }
