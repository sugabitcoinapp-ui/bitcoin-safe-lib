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
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any, Optional, TypeVar

_T = TypeVar("_T", covariant=True)


class LoopInThread:
    """
    Runs an asyncio event loop in a background thread,
    and cleanly cancels and shuts it down on stop() or on exiting a `with` block.
    """

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self.start()

    def get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop:
            return self._loop
        else:
            return self.start()

    def run_background(self, coro: Coroutine[Any, Any, _T]) -> Future[_T]:
        return asyncio.run_coroutine_threadsafe(coro, self.get_loop())

    def run_foreground(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """Schedule on the background loop and block until done."""
        fut = self.run_background(coro)
        return fut.result()

    def start(self) -> asyncio.AbstractEventLoop:
        """
        Create and start the background loop/thread.
        Returns the new event loop.
        """
        if self._loop is not None:
            raise RuntimeError("LoopInThread is already running")
        # create a fresh loop
        self._loop = asyncio.new_event_loop()
        # spin up the thread
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name="AsyncioLoopThread")
        self._thread.start()
        return self._loop

    def stop(self) -> None:
        """
        Cancel all tasks, stop the loop, join the thread, and close the loop.
        """
        if not self._loop or not self._thread:
            return  # nothing to do

        # schedule our shutdown coroutine on the loop
        shutdown_future = asyncio.run_coroutine_threadsafe(self._shutdown_coroutines(), self._loop)
        try:
            shutdown_future.result()
        except Exception:
            pass  # ignore any exceptions during shutdown

        # ask the loop to stop, wait for thread exit, then close
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop.close()

        # clean up
        self._loop = None
        self._thread = None

    def __enter__(self) -> asyncio.AbstractEventLoop:
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    async def _shutdown_coroutines(self):
        """
        Cancel all running tasks except this one, and wait for them to finish.
        """
        # on Python 3.7+ current_task() no longer takes loop=, but we can locate this task
        current = asyncio.current_task()
        # gather every other task
        tasks = [t for t in asyncio.all_tasks(loop=self._loop) if t is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
