from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import pytest
from chatkit.types import (
    AssistantMessageContent,
    AssistantMessageItem,
    InferenceOptions,
    ThreadMetadata,
    UserMessageItem,
    UserMessageTextContent,
)

from app.redis_store import RedisStore


class FakeRedis:
    def __init__(self) -> None:
        self._kv: Dict[str, bytes] = {}
        self._zsets: Dict[str, Dict[str, float]] = defaultdict(dict)
        self._lists: Dict[str, List[str]] = defaultdict(list)

    async def set(self, key: str, value: str | bytes) -> bool:
        if isinstance(value, str):
            value = value.encode("utf-8")
        self._kv[key] = value
        return True

    async def get(self, key: str) -> bytes | None:
        return self._kv.get(key)

    async def mget(self, keys: List[str]) -> List[bytes | None]:
        return [self._kv.get(key) for key in keys]

    async def exists(self, key: str) -> int:
        return int(key in self._kv or key in self._lists or key in self._zsets)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self._kv:
                del self._kv[key]
                removed += 1
            if key in self._lists:
                del self._lists[key]
                removed += 1
            if key in self._zsets:
                del self._zsets[key]
                removed += 1
        return removed

    async def zadd(self, key: str, mapping: Dict[str, float]) -> int:
        zset = self._zsets[key]
        for member, score in mapping.items():
            zset[member] = score
        return len(mapping)

    async def zrange(self, key: str, start: int, end: int) -> List[bytes]:
        items: List[Tuple[str, float]] = sorted(
            self._zsets.get(key, {}).items(),
            key=lambda entry: (entry[1], entry[0]),
        )
        if end == -1:
            end = len(items) - 1
        if end < start:
            return []
        sliced = items[start : end + 1]
        return [member.encode("utf-8") for member, _ in sliced]

    async def zrem(self, key: str, member: str) -> int:
        if member in self._zsets.get(key, {}):
            del self._zsets[key][member]
            return 1
        return 0

    async def lrange(self, key: str, start: int, end: int) -> List[bytes]:
        values = self._lists.get(key, [])
        if end == -1 or end >= len(values):
            end = len(values) - 1
        if end < start or start >= len(values):
            return []
        sliced = values[start : end + 1]
        return [value.encode("utf-8") for value in sliced]

    async def rpush(self, key: str, value: str) -> int:
        self._lists[key].append(value)
        return len(self._lists[key])

    async def lpos(self, key: str, value: str) -> int | None:
        values = self._lists.get(key, [])
        try:
            return values.index(value)
        except ValueError:
            return None

    async def lrem(self, key: str, count: int, value: str) -> int:
        values = self._lists.get(key, [])
        removed = 0
        if count == 0:
            count = len(values)
        new_values: List[str] = []
        for current in values:
            if current == value and removed < count:
                removed += 1
                continue
            new_values.append(current)
        if removed:
            self._lists[key] = new_values
        return removed

    async def close(self) -> None:
        return None


def _thread_metadata(thread_id: str) -> ThreadMetadata:
    return ThreadMetadata(
        id=thread_id,
        created_at=datetime.now(timezone.utc),
    )


def _user_message(thread_id: str, message_id: str, text: str) -> UserMessageItem:
    return UserMessageItem(
        id=message_id,
        thread_id=thread_id,
        created_at=datetime.now(timezone.utc),
        type="user_message",
        content=[UserMessageTextContent(text=text)],
        inference_options=InferenceOptions(),
    )


def _assistant_message(thread_id: str, message_id: str, text: str) -> AssistantMessageItem:
    return AssistantMessageItem(
        id=message_id,
        thread_id=thread_id,
        created_at=datetime.now(timezone.utc),
        type="assistant_message",
        content=[AssistantMessageContent(text=text)],
    )


@pytest.mark.asyncio
async def test_save_and_list_threads() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    context: dict[str, Any] = {"user_id": "user_a"}

    metadata = _thread_metadata("thr_test")
    await store.save_thread(metadata, context)

    loaded = await store.load_thread(metadata.id, context)
    assert loaded.id == metadata.id

    page = await store.load_threads(limit=5, after=None, order="asc", context=context)
    assert [thread.id for thread in page.data] == [metadata.id]
    assert not page.has_more


@pytest.mark.asyncio
async def test_item_crud_flow() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)
    context: dict[str, Any] = {"user_id": "user_a"}
    thread_id = "thr_items"

    metadata = _thread_metadata(thread_id)
    await store.save_thread(metadata, context)

    user_item = _user_message(thread_id, "msg_user", "Hello there")
    assistant_item = _assistant_message(thread_id, "msg_assistant", "Hi back")

    await store.add_thread_item(thread_id, user_item, context)
    await store.add_thread_item(thread_id, assistant_item, context)

    page = await store.load_thread_items(
        thread_id, after=None, limit=10, order="asc", context=context
    )
    assert [item.id for item in page.data] == ["msg_user", "msg_assistant"]

    updated = assistant_item.model_copy(
        update={"content": [AssistantMessageContent(text="Updated")]}
    )
    await store.save_item(thread_id, updated, context)

    loaded_item = await store.load_item(thread_id, "msg_assistant", context)
    assert loaded_item.content[0].text == "Updated"

    await store.delete_thread_item(thread_id, "msg_user", context)
    items_after_delete = await store.load_thread_items(
        thread_id, after=None, limit=10, order="asc", context=context
    )
    assert [item.id for item in items_after_delete.data] == ["msg_assistant"]

    await store.delete_thread(thread_id, context)
    page_after_delete = await store.load_threads(limit=5, after=None, order="asc", context=context)
    assert page_after_delete.data == []


@pytest.mark.asyncio
async def test_user_isolation() -> None:
    redis = FakeRedis()
    store = RedisStore(redis)

    context_a: dict[str, Any] = {"user_id": "alice"}
    context_b: dict[str, Any] = {"user_id": "bob"}

    thread_id = "thr_shared"

    await store.save_thread(_thread_metadata(thread_id), context_a)
    await store.save_thread(_thread_metadata(thread_id), context_b)

    await store.add_thread_item(thread_id, _user_message(thread_id, "msg_a1", "Hey"), context_a)
    await store.add_thread_item(thread_id, _user_message(thread_id, "msg_b1", "Hello"), context_b)

    page_a = await store.load_thread_items(thread_id, None, 10, "asc", context_a)
    page_b = await store.load_thread_items(thread_id, None, 10, "asc", context_b)

    assert [item.id for item in page_a.data] == ["msg_a1"]
    assert [item.id for item in page_b.data] == ["msg_b1"]

    threads_a = await store.load_threads(limit=5, after=None, order="asc", context=context_a)
    threads_b = await store.load_threads(limit=5, after=None, order="asc", context=context_b)

    assert [thread.id for thread in threads_a.data] == [thread_id]
    assert [thread.id for thread in threads_b.data] == [thread_id]
