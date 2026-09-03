# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/zujuan/_store_impl.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

# @Desc    : 组卷网数据存储实现类
from typing import Dict

from sqlalchemy import select

import config
from base.base_crawler import AbstractStore
from database.models import ZujuanQuestion
from database.db_session import get_session
from database.mongodb_store_base import MongoDBStoreBase
from tools import utils
from tools.async_file_writer import AsyncFileWriter
from var import crawler_type_var


class ZuJuanCsvStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="zujuan", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_to_csv(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        # 组卷网题库没有评论维度
        pass

    async def store_creator(self, creator: Dict):
        # 组卷网题库没有创作者维度
        pass


class ZuJuanJsonStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="zujuan", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_single_item_to_json(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        pass

    async def store_creator(self, creator: Dict):
        pass


class ZuJuanJsonlStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="zujuan", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_to_jsonl(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        pass

    async def store_creator(self, creator: Dict):
        pass


class ZuJuanDbStoreImplement(AbstractStore):
    async def store_content(self, content_item: Dict):
        """题目入库，按 question_id 去重更新"""
        question_id = content_item.get("question_id")
        async with get_session() as session:
            stmt = select(ZujuanQuestion).where(ZujuanQuestion.question_id == question_id)
            res = await session.execute(stmt)
            db_question = res.scalar_one_or_none()
            if db_question:
                for key, value in content_item.items():
                    setattr(db_question, key, value)
            else:
                session.add(ZujuanQuestion(**content_item))
            await session.commit()

    async def store_comment(self, comment_item: Dict):
        pass

    async def store_creator(self, creator: Dict):
        pass


class ZuJuanSqliteStoreImplement(ZuJuanDbStoreImplement):
    """组卷网 sqlite 存储实现"""

    pass


class ZuJuanMongoStoreImplement(AbstractStore):
    """组卷网 MongoDB 存储实现"""

    def __init__(self):
        self.mongo_store = MongoDBStoreBase(collection_prefix="zujuan")

    async def store_content(self, content_item: Dict):
        question_id = content_item.get("question_id")
        if not question_id:
            return
        await self.mongo_store.save_or_update(
            collection_suffix="contents",
            query={"question_id": question_id},
            data=content_item,
        )
        utils.logger.info(f"[ZuJuanMongoStoreImplement.store_content] Saved question {question_id} to MongoDB")

    async def store_comment(self, comment_item: Dict):
        pass

    async def store_creator(self, creator: Dict):
        pass


class ZuJuanExcelStoreImplement:
    """组卷网 Excel 存储实现 - 全局单例"""

    def __new__(cls, *args, **kwargs):
        from store.excel_store_base import ExcelStoreBase

        return ExcelStoreBase.get_instance(
            platform="zujuan",
            crawler_type=crawler_type_var.get(),
        )
