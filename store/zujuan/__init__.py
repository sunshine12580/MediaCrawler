# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/zujuan/__init__.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网存储分发

和其它平台不同的是这里是**双写**：每道题先写一份原始 JSONL 快照（含整张卡片原文，
供以后离线重解析），再按 SAVE_DATA_OPTION 写结构化存储。快照的日期决定
questions.raw_day，所以顺序不能反。
"""

from typing import Optional

import config
from base.base_crawler import AbstractStore
from model.m_zujuan import ZujuanQuestion
from tools import utils

from ._store_impl import (
    ZuJuanCsvStoreImplement,
    ZuJuanDbStoreImplement,
    ZuJuanJsonStoreImplement,
    ZuJuanRawJsonlStoreImplement,
    ZuJuanSqliteStoreImplement,
    now_iso,
)

# 分片状态要在整个进程里共享，不能每道题新建一个
_raw_store: Optional[ZuJuanRawJsonlStoreImplement] = None


def get_raw_store() -> ZuJuanRawJsonlStoreImplement:
    global _raw_store
    if _raw_store is None:
        _raw_store = ZuJuanRawJsonlStoreImplement()
    return _raw_store


class ZuJuanStoreFactory:
    STORES = {
        "csv": ZuJuanCsvStoreImplement,
        "json": ZuJuanJsonStoreImplement,
        "jsonl": ZuJuanRawJsonlStoreImplement,
        "db": ZuJuanDbStoreImplement,
        "mysql": ZuJuanDbStoreImplement,
        "postgres": ZuJuanDbStoreImplement,
        "sqlite": ZuJuanSqliteStoreImplement,
    }

    @staticmethod
    def create_store() -> AbstractStore:
        save_option = config.SAVE_DATA_OPTION
        if save_option == "jsonl":
            # 原始快照本来就一直在写，别再重复写一份
            return get_raw_store()
        store_class = ZuJuanStoreFactory.STORES.get(save_option)
        if not store_class:
            raise ValueError(
                f"[ZuJuanStoreFactory.create_store] 组卷网不支持 --save_data_option {save_option}，"
                f"可选：{' / '.join(sorted(ZuJuanStoreFactory.STORES))}。"
                " 知识点和来源试卷是多对多数据，只有 db/sqlite/postgres（关联表）"
                "和 jsonl（原始快照）能完整表达"
            )
        return store_class()


async def update_zujuan_question(question: ZujuanQuestion):
    """
    保存一道组卷网题目：原始 JSONL 快照 + 结构化存储。

    Args:
        question: 解析出来的题目模型
    """
    question.grade = getattr(config, "ZUJUAN_GRADE", "middle")
    question.captured_at = now_iso()

    write_raw = getattr(config, "ZUJUAN_ENABLE_RAW_JSONL", True)
    if write_raw:
        raw_store = get_raw_store()
        # 先定下写哪个分片，raw_day 要跟着一起入库
        question.raw_day = raw_store.raw_day
        await raw_store.store_content(question)

    utils.logger.info(
        f"[store.zujuan.update_zujuan_question] question_id: {question.question_id}, "
        f"qtype: {question.qtype_full or question.qtype}, "
        f"difficulty: {question.difficulty}({question.score_rate}), "
        f"knowledge: {question.knowledge_id}, raw_day: {question.raw_day}"
    )

    store = ZuJuanStoreFactory.create_store()
    if write_raw and isinstance(store, ZuJuanRawJsonlStoreImplement):
        # SAVE_DATA_OPTION=jsonl 且快照已开：上面那一次写就是全部产出
        return
    await store.store_content(question)
