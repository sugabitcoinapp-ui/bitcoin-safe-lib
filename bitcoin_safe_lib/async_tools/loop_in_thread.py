#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see https://www.gnu.org/licenses/gpl-3.0.html
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import asyncio
import sys
import threading
from concurrent.futures import CancelledError, Future
from enum import Enum, auto
from typing import (
    Any,
    Awaitable,
    Callable,
    Coroutine,
    Dict,
    Iterable,
    List,
    Optional,
    TypeVar,
)

from PyQt6.QtCore import QObject, Qt, pyqtSignal


class _GuiInvoker(QObject):
    """
    Queues function calls onto the Qt main thread via a signal/slot.
    """

    invoke = pyqtSignal(object, tuple)

    def __init__(self):
        super().__init__()
        # Always queued, even if emitted from main thread
        self.invoke.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    @staticmethod
    def _dispatch(func, args):
        func(*args)


_GUI_INVOKER = _GuiInvoker()

_T = TypeVar("_T")
_OnSuccess = Callable[[Any], None]
_OnDone = Callable[[Any], None]
_OnError = Callable[[tuple], None]
_Cancel = Callable[[], None]


class MultipleStrategy(Enum):
    QUEUE = auto()
    REJECT_NEW_TASK = auto()
    CANCEL_OLD_TASK = auto()
    RUN_INDEPENDENT = auto()


class LoopInThread:
    """
    Runs an asyncio event loop in a daemon thread with optional key-based task strategies.

    Methods:
      - run_background: schedules a coroutine, returns concurrent.Future.
      - run_parallel: returns an asyncio.Future you can `await` from async code.
      - run_foreground: blocks until done.
      - run_task: callback style.
    """

    def __init__(self, autostart: bool = True):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._tasks: Dict[Future[Any], _Cancel] = {}
        self._key_tasks: Dict[str, List[Future[Any]]] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

        if autostart:
            self.start()

    def _get_bucket(self, key: str):
        with self._global_lock:
            bucket = self._key_tasks.setdefault(key, [])
            lock = self._locks.setdefault(key, threading.Lock())
        return bucket, lock

    def start(self) -> asyncio.AbstractEventLoop:
        if self._loop:
            raise RuntimeError("LoopInThread already started")
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True, name="AsyncioLoopThread")
        thread.start()
        self._loop = loop
        self._thread = thread
        return loop

    def get_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop or self.start()

    def _schedule(self, coro: Coroutine[Any, Any, _T]) -> Future[_T]:
        return asyncio.run_coroutine_threadsafe(coro, self.get_loop())

    def run_background(
        self,
        coro: Coroutine[Any, Any, _T],
        key: Optional[str] = None,
        multiple_strategy: MultipleStrategy = MultipleStrategy.RUN_INDEPENDENT,
    ) -> Future[_T]:
        # No key logic: fire-and-forget on the loop
        if key is None or multiple_strategy is MultipleStrategy.RUN_INDEPENDENT:
            return self._schedule(coro)

        bucket, lock = self._get_bucket(key)
        cancel_list: List[Future[Any]] = []

        with lock:
            if multiple_strategy is MultipleStrategy.REJECT_NEW_TASK:
                if any(not f.done() for f in bucket):
                    fut = Future()
                    fut.set_running_or_notify_cancel()
                    fut.cancel()
                    return fut

            if multiple_strategy is MultipleStrategy.CANCEL_OLD_TASK and bucket:
                cancel_list = list(bucket)
                bucket.clear()

            if multiple_strategy is MultipleStrategy.QUEUE and bucket:
                parent = bucket[-1]

                async def wrapper() -> _T:
                    try:
                        await asyncio.wrap_future(parent)
                    except Exception:
                        pass
                    return await coro

                scheduled = wrapper()
            else:
                scheduled = coro

            fut = self._schedule(scheduled)
            bucket.append(fut)

            def cleanup(done: Future[Any], _bucket=bucket, _lock=lock):
                with _lock:
                    if done in _bucket:
                        _bucket.remove(done)
                    if not _bucket:
                        with self._global_lock:
                            self._key_tasks.pop(key, None)
                            self._locks.pop(key, None)

            fut.add_done_callback(cleanup)

        # cancel old tasks outside the lock to avoid deadlock
        for old in cancel_list:
            self.cancel_task(old)

        return fut

    def run_parallel(
        self,
        coros: Iterable[Coroutine[Any, Any, _T]],
        key: Optional[str] = None,
        multiple_strategy: MultipleStrategy = MultipleStrategy.RUN_INDEPENDENT,
    ) -> Awaitable[List[_T]]:
        """
        Schedule multiple coroutines under the same key/strategy.
        Returns an asyncio.Future you can `await` (it wraps the concurrent.Future).
        """
        # Schedule each on the loop (concurrent.Future)
        futures = [self.run_background(c, key=key, multiple_strategy=multiple_strategy) for c in coros]

        async def gather_all() -> List[_T]:
            async_futs = [asyncio.wrap_future(f) for f in futures]
            return await asyncio.gather(*async_futs)

        # Schedule gather_all on the loop and wrap for awaiting
        concurrent = self._schedule(gather_all())
        return asyncio.wrap_future(concurrent)

    def run_foreground(self, coro: Coroutine[Any, Any, _T]) -> _T:
        # Blocks calling thread until coro completes
        return self._schedule(coro).result()

    def run_task(
        self,
        coro: Coroutine[Any, Any, _T],
        on_success: Optional[_OnSuccess] = None,
        on_done: Optional[_OnDone] = None,
        on_error: Optional[_OnError] = None,
        cancel: Optional[_Cancel] = None,
        key: Optional[str] = None,
        multiple_strategy: MultipleStrategy = MultipleStrategy.RUN_INDEPENDENT,
    ) -> Future[_T]:
        fut = self.run_background(coro, key=key, multiple_strategy=multiple_strategy)
        if cancel:
            self._tasks[fut] = cancel

        def _handle(f: Future[_T]):
            if f.cancelled():
                return
            try:
                result = f.result()
            except CancelledError:
                return
            except Exception:
                if on_error:
                    self._invoke_main(on_error, sys.exc_info())
            else:
                if on_success:
                    self._invoke_main(on_success, result)
            finally:
                if on_done:
                    self._invoke_main(on_done, result if not f.cancelled() else None)
                cb = self._tasks.pop(f, None)
                if cb:
                    self._invoke_main(cb)

        fut.add_done_callback(_handle)
        return fut

    def cancel_task(self, fut: Future[Any]) -> None:
        fut.cancel()
        cb = self._tasks.pop(fut, None)
        if cb:
            self._invoke_main(cb)

    def stop(self) -> None:
        # Cancel all pending callbacks
        for fut in list(self._tasks):
            self.cancel_task(fut)
        if self._loop:
            # Schedule shutdown without blocking
            asyncio.run_coroutine_threadsafe(self._shutdown_coroutines(), self._loop)
            self._loop.call_soon_threadsafe(self._loop.stop)
        # Daemon thread will exit when loop stops
        self._loop = None
        self._thread = None

    async def _shutdown_coroutines(self):
        current = asyncio.current_task()
        tasks = [t for t in asyncio.all_tasks(loop=self._loop) if t is not current]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _invoke_main(func: Callable, *args):
        _GUI_INVOKER.invoke.emit(func, args)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
