"""좁은 터미널에서도 한글과 긴 설치 경로를 읽을 수 있게 출력한다."""
import shutil
import unicodedata


def display_width(text: str) -> int:
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def wrap_console_text(text: str, *, indent: str = "", width: int | None = None) -> str:
    width = width or max(20, min(110, shutil.get_terminal_size((96, 24)).columns))
    available = max(1, width - display_width(indent))
    lines = []
    for source in str(text).splitlines() or [""]:
        line = ""
        used = 0
        for char in source.expandtabs(4):
            size = display_width(char)
            if used + size > available and line:
                lines.append(indent + line)
                line, used = "", 0
            line += char
            used += size
        lines.append(indent + line)
    return "\n".join(lines)


def print_check(status: str, name: str, detail: str, *, path: str | None = None) -> None:
    label = name + " " * max(1, 12 - display_width(name))
    print(wrap_console_text(f"[{status}] {label}{detail}", indent="  "))
    if path:
        print(wrap_console_text(f"경로: {path}", indent="         "))
