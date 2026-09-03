# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/cache/abs_cache.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#



# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Name    : Programmer AJiang-Relakkes
# @Time    : 2024/6/2 11:06
# @Desc    : Abstract class

from abc import ABC, abstractmethod
from typing import Any, List, Optional


class AbstractCache(ABC):

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """
        Get the value of a key from the cache.
        This is an abstract method. Subclasses must implement this method.
        :param key: The key
        :return:
        """
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, value: Any, expire_time: int) -> None:
        """
        Set the value of a key in the cache.
        This is an abstract method. Subclasses must implement this method.
        :param key: The key
        :param value: The value
        :param expire_time: Expiration time
        :return:
        """
        raise NotImplementedError

    @abstractmethod
    def keys(self, pattern: str) -> List[str]:
        """
        Get all keys matching the pattern
        :param pattern: Matching pattern
        :return:
        """
        raise NotImplementedError
