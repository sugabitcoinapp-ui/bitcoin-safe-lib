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


import logging
from typing import Any, Callable, List, Protocol, Tuple, runtime_checkable

from PyQt6.QtCore import QObject, pyqtBoundSignal

logger = logging.getLogger(__name__)


@runtime_checkable
class SignalProtocol(Protocol):
    connect: Callable[..., Any]
    disconnect: Callable[..., Any]


class SignalTools:
    @classmethod
    def disconnect_all_signals_from(cls, object_with_bound_signals: QObject) -> None:
        """Finds any qtBoundSignal (or TypedPyQtSignal) on the given QObject
        and removes all of its connections.
        """

        def _safe_disconnect(signal: SignalProtocol) -> None:
            # disconnect() without args breaks one connection at a time
            while True:
                try:
                    signal.disconnect()
                except TypeError:
                    break

        for name in dir(object_with_bound_signals):
            if name == "destroyed":
                continue
            try:
                sig = getattr(object_with_bound_signals, name)
            except Exception:
                continue
            if isinstance(sig, SignalProtocol):
                _safe_disconnect(sig)

    @classmethod
    def connect_signal(
        cls,
        signal: SignalProtocol,
        handler: Callable[..., Any],
        **kwargs: Any,
    ) -> Tuple[SignalProtocol, Callable[..., Any]]:
        signal.connect(handler, **kwargs)
        return (signal, handler)

    @classmethod
    def connect_signal_and_append(
        cls,
        connected_signals: List[Tuple[SignalProtocol, Callable[..., Any]]],
        signal: SignalProtocol,
        handler: Callable[..., Any],
        **kwargs: Any,
    ) -> None:
        signal.connect(handler, **kwargs)
        connected_signals.append((signal, handler))

    @classmethod
    def disconnect_signal(
        cls,
        signal: SignalProtocol,
        handler: Callable[..., Any] | pyqtBoundSignal | SignalProtocol,
    ) -> None:
        try:
            signal.disconnect(handler)
        except Exception:
            logger.debug(f"Could not disconnect {signal!r} from {handler!r}")

    @classmethod
    def disconnect_signals(
        cls,
        connected_signals: List[Tuple[SignalProtocol, Callable[..., Any] | pyqtBoundSignal | SignalProtocol]],
    ) -> None:
        while connected_signals:
            sig, handler = connected_signals.pop()
            cls.disconnect_signal(sig, handler)


class SignalTracker:
    def __init__(self) -> None:
        self._connected_signals: List[
            Tuple[SignalProtocol, Callable[..., Any] | pyqtBoundSignal | SignalProtocol]
        ] = []

    def connect(
        self,
        signal: SignalProtocol,
        handler: Callable[..., Any] | pyqtBoundSignal | SignalProtocol,
        **kwargs: Any,
    ) -> None:
        signal.connect(handler, **kwargs)
        self._connected_signals.append((signal, handler))

    def disconnect_all(self) -> None:
        SignalTools.disconnect_signals(self._connected_signals)
