from __future__ import annotations

import asyncio
import itertools
import uuid
from collections.abc import Awaitable, Callable


class PriorityJobQueue:
    def __init__(
        self,
        runner: Callable[[uuid.UUID, bool], Awaitable[None]],
        *,
        worker_count: int,
    ) -> None:
        self.runner = runner
        self.worker_count = max(1, worker_count)
        self.queue: asyncio.PriorityQueue[tuple[int, int, uuid.UUID | None, bool]] = asyncio.PriorityQueue()
        self.counter = itertools.count()
        self.workers: list[asyncio.Task] = []

    async def start(self) -> None:
        if self.workers:
            return
        self.workers = [asyncio.create_task(self._worker(), name=f"emotionos-studio-{index}") for index in range(self.worker_count)]

    async def close(self) -> None:
        for _ in self.workers:
            await self.queue.put((10_000, next(self.counter), None, False))
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

    async def enqueue(self, job_id: uuid.UUID, *, priority: int, force: bool = False) -> None:
        await self.queue.put((priority, next(self.counter), job_id, force))

    async def _worker(self) -> None:
        while True:
            _, _, job_id, force = await self.queue.get()
            try:
                if job_id is None:
                    return
                await self.runner(job_id, force)
            finally:
                self.queue.task_done()