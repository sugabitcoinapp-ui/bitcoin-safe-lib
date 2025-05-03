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

import csv
import gzip
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional, Tuple

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

from .util import is_dark_mode


class SvgTools:
    def __init__(self, resource_path: Callable[..., str]) -> None:
        self.resource_path = resource_path

    def icon_path(self, icon_basename: str) -> str:
        return self.resource_path("gui", "icons", icon_basename)

    @classmethod
    def read_source_file(cls, svg_path: str) -> str:
        if svg_path.lower().endswith(".svgz"):
            # Open the svgz file in text mode with gzip
            with gzip.open(svg_path, "rt", encoding="utf-8") as file:
                return file.read()
        else:
            # Open the file normally
            with open(svg_path, "r", encoding="utf-8") as file:
                return file.read()

    def auto_theme_svg(self, svg_content: str, color: QColor | None = None) -> str:
        theme_file = self.icon_path("theme.csv")
        with open(theme_file, "r") as file:
            csv_reader = csv.reader(file)
            all_rows = [row for row in csv_reader if row]
            header, csv_rows = all_rows[0], all_rows[1:]

        if color is None:
            color = QApplication.palette().color(QPalette.ColorRole.WindowText)
        # Replace "currentColor" in the SVG with the desired color
        replace_strings = csv_rows + [["WindowText", color.name(), color.name()]]

        for org, light_mode, dark_mode in replace_strings:
            svg_content = svg_content.replace(org, dark_mode if is_dark_mode() else light_mode)
        return svg_content

    @classmethod
    def svg_to_pixmap(cls, svg_data: str, size=(256, 256)) -> QPixmap:
        renderer = QSvgRenderer(QByteArray(svg_data.encode("utf-8")))
        pixmap = QPixmap(*size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap

    @classmethod
    def svg_to_icon(cls, svg_content: str, size=(256, 256)) -> QIcon:
        # Create an icon from the pixmap
        pixmap = cls.svg_to_pixmap(svg_content, size)
        return QIcon(pixmap)

    @lru_cache(maxsize=1000)
    def get_QIcon(
        self, icon_basename: Optional[str], auto_theme: bool = True, size: Tuple[int, int] = (256, 256)
    ) -> QIcon:
        if not icon_basename:
            return QIcon()
        icon_file = Path(self.icon_path(icon_basename))
        if not icon_file.exists():
            return QIcon()

        if icon_file.suffix.lstrip(".") in ["svg", "svgz"]:
            svg_content = self.read_source_file(str(icon_file))
            return self.svg_to_icon(
                self.auto_theme_svg(svg_content) if auto_theme else svg_content, size=size
            )
        else:
            return QIcon(str(icon_file))

    @lru_cache(maxsize=1000)
    def get_pixmap(
        self, icon_basename: Optional[str], auto_theme: bool = True, size: Tuple[int, int] = (256, 256)
    ) -> QPixmap:
        if not icon_basename:
            return QPixmap()
        icon_file = Path(self.icon_path(icon_basename))
        if not icon_file.exists():
            return QPixmap()

        if icon_file.suffix.lstrip(".") in ["svg", "svgz"]:
            svg_content = self.read_source_file(str(icon_file))
            return self.svg_to_pixmap(
                self.auto_theme_svg(svg_content) if auto_theme else svg_content, size=size
            )
        else:
            return QPixmap(str(icon_file))
