"""Mouse dragging shared by floating chat windows."""

from textual import events
from textual.containers import Vertical


class DraggableWindow(Vertical):
    """Drag the top border or title row; leave the body available for selection."""

    DEFAULT_CSS = """
    DraggableWindow { position: absolute; }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._window_position: tuple[int, int] | None = None
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._dragged = False

    def position_window(self, screen=None, width=None, height=None) -> None:
        screen = screen or self.screen.size
        width = self.outer_size.width if width is None else width
        height = self.outer_size.height if height is None else height
        x, y = self._window_position or (
            max((screen.width - width) // 2, 0),
            max((screen.height - height) // 2, 0),
        )
        position = (max(0, min(x, screen.width - width)),
                    max(0, min(y, screen.height - height)))
        if self._window_position is not None:
            self._window_position = position
        self.styles.offset = position

    def reset_position(self) -> None:
        self._end_drag()
        self._window_position = None
        self._dragged = False

    def on_resize(self, event: events.Resize) -> None:
        self.position_window()

    def drag_handle(self, event: events.MouseDown) -> bool:
        return (self.region.x <= event.screen_x < self.region.right
                and self.region.y <= event.screen_y <= self.content_region.y)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragged = False
        if event.button != 1 or not self.drag_handle(event):
            return
        event.stop()
        event.prevent_default()
        self._drag_origin = (event.screen_x, event.screen_y,
                             self.region.x, self.region.y)
        self.capture_mouse()

    def _move_window(self, event: events.MouseEvent) -> None:
        if self._drag_origin is None:
            return
        mouse_x, mouse_y, x, y = self._drag_origin
        dx, dy = event.screen_x - mouse_x, event.screen_y - mouse_y
        if dx or dy:
            self._dragged = True
            self._window_position = (x + dx, y + dy)
            self.position_window()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag_origin is not None:
            event.stop()
            event.prevent_default()
            self._move_window(event)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag_origin is not None:
            event.stop()
            event.prevent_default()
            self._move_window(event)
            self._end_drag()

    def _end_drag(self) -> None:
        if self._drag_origin is not None:
            self.release_mouse()
            self._drag_origin = None

    def on_click(self, event: events.Click) -> None:
        if self._dragged:
            event.stop()
            event.prevent_default()
            self._dragged = False

    def on_unmount(self) -> None:
        self._end_drag()
