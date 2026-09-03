# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/cache/cache_factory.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#



# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Name    : Programmer AJiang-Relakkes
# @Time    : 2024/6/2 11:23
# @Desc    :


class CacheFactory:
    """
    Cache factory class
    """

    @staticmethod
    def create_cache(cache_type: str, *args, **kwargs):
        """
        Create cache object
        :param cache_type: Cache type
        :param args: Arguments
        :param kwargs: Keyword arguments
        :return:
        """
        if cache_type == 'memory':
            from .local_cache import ExpiringLocalCache
            return ExpiringLocalCache(*args, **kwargs)
        elif cache_type == 'redis':
            from .redis_cache import RedisCache
            return RedisCache()
        else:
            raise ValueError(f'Unknown cache type: {cache_type}')
