from __future__ import annotations

from luvatrix.app import App


class HelloWorldApp(App):
    def render(self) -> None:
        width = self.display.width_px
        height = self.display.height_px
        size = max(1, min(width, height) // 4)
        x = float((width - size) // 2)
        y = float((height - size) // 2)
        with self.frame(clear=(30, 30, 46, 255)) as frame:
            frame.rect(x=x, y=y, width=float(size), height=float(size), color=(255, 255, 255, 255))


def create() -> HelloWorldApp:
    return HelloWorldApp()
