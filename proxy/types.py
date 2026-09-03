# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/proxy/types.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#



# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2024/4/5 10:18
# @Desc    : Basic types
import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ProviderNameEnum(Enum):
    KUAI_DAILI_PROVIDER: str = "kuaidaili"
    WANDOU_HTTP_PROVIDER: str = "wandouhttp"
    STATIC_PROVIDER: str = "static"


class IpInfoModel(BaseModel):
    """Unified IP model"""

    ip: str = Field(title="ip")
    port: int = Field(title="port")
    user: str = Field(title="Username for IP proxy authentication")
    protocol: str = Field(default="https://", title="Protocol for proxy IP")
    password: str = Field(title="Password for IP proxy authentication user")
    expired_time_ts: Optional[int] = Field(default=None, title="IP expiration time")

    def is_expired(self, buffer_seconds: int = 30) -> bool:
        """
        Check if proxy IP has expired
        Args:
            buffer_seconds: Buffer time (seconds), how many seconds ahead to consider expired to avoid critical time request failures
        Returns:
            bool: True means expired or about to expire, False means still valid
        """
        if self.expired_time_ts is None:
            return False
        current_ts = int(time.time())
        return current_ts >= (self.expired_time_ts - buffer_seconds)
