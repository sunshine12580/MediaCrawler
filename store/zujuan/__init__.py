# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/zujuan/__init__.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

# @Desc    : 组卷网存储入口
import config
from base.base_crawler import AbstractStore
from model.m_zujuan import ZujuanQuestion as ZujuanQuestionItem
from tools import utils

from ._store_impl import *


class ZuJuanStoreFactory:
    STORES = {
        "csv": ZuJuanCsvStoreImplement,
        "db": ZuJuanDbStoreImplement,
        "postgres": ZuJuanDbStoreImplement,
        "json": ZuJuanJsonStoreImplement,
        "jsonl": ZuJuanJsonlStoreImplement,
        "sqlite": ZuJuanSqliteStoreImplement,
        "mongodb": ZuJuanMongoStoreImplement,
        "excel": ZuJuanExcelStoreImplement,
    }

    @staticmethod
    def create_store() -> AbstractStore:
        store_class = ZuJuanStoreFactory.STORES.get(config.SAVE_DATA_OPTION)
        if not store_class:
            raise ValueError(
                "[ZuJuanStoreFactory.create_store] Invalid save option only supported csv or db or json or jsonl or sqlite or mongodb or excel ..."
            )
        return store_class()


async def update_zujuan_question(question_item: ZujuanQuestionItem):
    """
    保存一道组卷网题目
    Args:
        question_item: 题目数据模型

    Returns:

    """
    save_question_item = question_item.model_dump()
    now_ts = utils.get_current_timestamp()
    save_question_item.update({"add_ts": now_ts, "last_modify_ts": now_ts})
    utils.logger.info(
        f"[store.zujuan.update_zujuan_question] question_id: {save_question_item.get('question_id')}, "
        f"type: {save_question_item.get('question_type')}, "
        f"content: {save_question_item.get('content_text', '')[:60]}"
    )
    await ZuJuanStoreFactory.create_store().store_content(save_question_item)
