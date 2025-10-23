from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, List

from chatkit.store import NotFoundError, Store
from chatkit.types import Attachment, Page, Thread, ThreadItem, ThreadMetadata
from pydantic import TypeAdapter
from redis.asyncio import Redis


def _metadata_key(thread_id: str) -> str:
    return f"thread:{thread_id}:metadata"


def _items_list_key(thread_id: str) -> str:
    return f"thread:{thread_id}:items"


def _item_key(thread_id: str, item_id: str) -> str:
    return f"thread:{thread_id}:item:{item_id}"


_THREAD_INDEX_KEY = "threads:index"


class RedisStore(Store[dict[str, Any]]):
    """Redis-backed ChatKit Store implementation."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def aclose(self) -> None:
        """Close the underlying Redis connection pool."""
        await self._redis.close()

    @staticmethod
    def _coerce_thread_metadata(thread: ThreadMetadata | Thread) -> ThreadMetadata:
        """Return thread metadata without any embedded items (openai-chatkit>=1.0)."""
        has_items = isinstance(thread, Thread) or "items" in getattr(
            thread, "model_fields_set", set()
        )
        if not has_items:
            return thread.model_copy(deep=True)

        data = thread.model_dump()
        data.pop("items", None)
        return ThreadMetadata(**data).model_copy(deep=True)

    @staticmethod
    def _ensure_created_at(metadata: ThreadMetadata) -> ThreadMetadata:
        if metadata.created_at is not None:
            return metadata
        now = datetime.now(timezone.utc)
        return metadata.model_copy(update={"created_at": now})

    @staticmethod
    def _dump_model(model: ThreadMetadata | ThreadItem) -> str:
        return json.dumps(model.model_dump(mode="json"), separators=(",", ":"))

    @staticmethod
    def _loads_metadata(value: bytes | None) -> ThreadMetadata:
        if value is None:
            raise NotFoundError("Thread metadata missing")
        data = json.loads(value.decode("utf-8"))
        return ThreadMetadata.model_validate(data)

    @staticmethod
    def _loads_item(value: bytes | None) -> ThreadItem:
        if value is None:
            raise NotFoundError("Thread item missing")
        data = json.loads(value.decode("utf-8"))
        return _ITEM_ADAPTER.validate_python(data)

    async def load_thread(self, thread_id: str, context: dict[str, Any]) -> ThreadMetadata:
        raw = await self._redis.get(_metadata_key(thread_id))
        if raw is None:
            raise NotFoundError(f"Thread {thread_id} not found")
        metadata = self._loads_metadata(raw)
        return metadata.model_copy(deep=True)

    async def save_thread(self, thread: ThreadMetadata, context: dict[str, Any]) -> None:
        metadata = self._coerce_thread_metadata(thread)
        metadata = self._ensure_created_at(metadata)

        encoded = self._dump_model(metadata)
        await self._redis.set(_metadata_key(metadata.id), encoded)

        created_at = metadata.created_at or datetime.now(timezone.utc)
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(timezone.utc)
        score = created_at.timestamp()
        await self._redis.zadd(_THREAD_INDEX_KEY, {metadata.id: score})

    async def load_threads(
        self,
        limit: int,
        after: str | None,
        order: str,
        context: dict[str, Any],
    ) -> Page[ThreadMetadata]:
        thread_ids = await self._redis.zrange(_THREAD_INDEX_KEY, 0, -1)
        sequence: List[str] = [thread_id.decode("utf-8") for thread_id in thread_ids]
        if order == "desc":
            sequence.reverse()

        start_index = 0
        if after:
            try:
                start_index = sequence.index(after) + 1
            except ValueError:
                start_index = 0

        slice_ids = sequence[start_index : start_index + limit + 1]
        has_more = len(slice_ids) > limit
        slice_ids = slice_ids[:limit]

        if not slice_ids:
            return Page(data=[], has_more=False, after=None)

        metadata_values = await self._redis.mget([_metadata_key(thread_id) for thread_id in slice_ids])
        threads: List[ThreadMetadata] = []
        for raw in metadata_values:
            if raw is None:
                continue
            threads.append(self._loads_metadata(raw))

        next_after = slice_ids[-1] if has_more else None
        return Page(
            data=[thread.model_copy(deep=True) for thread in threads],
            has_more=has_more,
            after=next_after,
        )

    async def delete_thread(self, thread_id: str, context: dict[str, Any]) -> None:
        items_list_key = _items_list_key(thread_id)
        item_ids = await self._redis.lrange(items_list_key, 0, -1)
        if item_ids:
            await self._redis.delete(*[_item_key(thread_id, item_id.decode("utf-8")) for item_id in item_ids])
        await self._redis.delete(items_list_key, _metadata_key(thread_id))
        await self._redis.zrem(_THREAD_INDEX_KEY, thread_id)

    async def _load_all_items(self, thread_id: str) -> List[ThreadItem]:
        item_ids = await self._redis.lrange(_items_list_key(thread_id), 0, -1)
        if not item_ids:
            return []

        keys = [_item_key(thread_id, item_id.decode("utf-8")) for item_id in item_ids]
        values = await self._redis.mget(keys)
        items: List[ThreadItem] = []
        for raw in values:
            if raw is None:
                continue
            items.append(self._loads_item(raw))
        return items

    def _order_items(self, items: Iterable[ThreadItem], order: str) -> List[ThreadItem]:
        sorted_items = sorted(
            (item.model_copy(deep=True) for item in items),
            key=lambda item: getattr(item, "created_at", datetime.now(timezone.utc)),
            reverse=(order == "desc"),
        )
        return sorted_items

    async def load_thread_items(
        self,
        thread_id: str,
        after: str | None,
        limit: int,
        order: str,
        context: dict[str, Any],
    ) -> Page[ThreadItem]:
        all_items = self._order_items(await self._load_all_items(thread_id), order)
        if after:
            index_map = {item.id: idx for idx, item in enumerate(all_items)}
            start = index_map.get(after, -1) + 1
        else:
            start = 0

        slice_items = all_items[start : start + limit + 1]
        has_more = len(slice_items) > limit
        slice_items = slice_items[:limit]
        next_after = slice_items[-1].id if has_more and slice_items else None
        return Page(
            data=[item.model_copy(deep=True) for item in slice_items],
            has_more=has_more,
            after=next_after,
        )

    async def add_thread_item(
        self, thread_id: str, item: ThreadItem, context: dict[str, Any]
    ) -> None:
        if not await self._redis.exists(_metadata_key(thread_id)):
            metadata = ThreadMetadata(
                id=thread_id,
                created_at=datetime.now(timezone.utc),
            )
            await self.save_thread(metadata, context)
        await self._write_item(thread_id, item, ensure_list=True)

    async def save_item(self, thread_id: str, item: ThreadItem, context: dict[str, Any]) -> None:
        await self._write_item(thread_id, item, ensure_list=False)

    async def _write_item(
        self,
        thread_id: str,
        item: ThreadItem,
        ensure_list: bool = False,
    ) -> None:
        item_id = item.id
        key = _item_key(thread_id, item_id)
        encoded = self._dump_model(item)
        await self._redis.set(key, encoded)

        list_key = _items_list_key(thread_id)
        position = await self._redis.lpos(list_key, item_id)
        if position is None:
            await self._redis.rpush(list_key, item_id)
        elif ensure_list:
            # ensure existing id stays in place when called from add_thread_item
            pass

    async def load_item(self, thread_id: str, item_id: str, context: dict[str, Any]) -> ThreadItem:
        raw = await self._redis.get(_item_key(thread_id, item_id))
        if raw is None:
            raise NotFoundError(f"Item {item_id} not found")
        item = self._loads_item(raw)
        return item.model_copy(deep=True)

    async def delete_thread_item(
        self, thread_id: str, item_id: str, context: dict[str, Any]
    ) -> None:
        await self._redis.lrem(_items_list_key(thread_id), 0, item_id)
        await self._redis.delete(_item_key(thread_id, item_id))

    async def save_attachment(
        self,
        attachment: Attachment,
        context: dict[str, Any],
    ) -> None:
        raise NotImplementedError(
            "RedisStore does not persist attachments. Provide a Store implementation "
            "that enforces authentication and authorization before enabling uploads."
        )

    async def load_attachment(
        self,
        attachment_id: str,
        context: dict[str, Any],
    ) -> Attachment:
        raise NotImplementedError(
            "RedisStore does not load attachments. Provide a Store implementation "
            "that enforces authentication and authorization before enabling uploads."
        )

    async def delete_attachment(self, attachment_id: str, context: dict[str, Any]) -> None:
        raise NotImplementedError(
            "RedisStore does not delete attachments because they are never stored."
        )
_ITEM_ADAPTER = TypeAdapter(ThreadItem)
