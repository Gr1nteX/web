import time
from pathlib import Path

CGROUP = Path("/sys/fs/cgroup")


def read(name: str) -> str | None:
    try:
        return (CGROUP / name).read_text()
    except OSError:
        return None


class Metrics:
    def __init__(self):
        self.last: tuple[int, float] | None = None

    @staticmethod
    def cpu_usage_usec() -> int | None:
        stat = read("cpu.stat")
        if stat:
            for line in stat.splitlines():
                if line.startswith("usage_usec"):
                    return int(line.split()[1])
        usage_ns = read("cpuacct/cpuacct.usage")
        return int(usage_ns) // 1000 if usage_ns else None

    def cpu_percent(self) -> float | None:
        usage = self.cpu_usage_usec()
        if usage is None:
            return None
        now = time.monotonic()
        previous, self.last = self.last, (usage, now)
        if previous is None:
            return None
        return round((usage - previous[0]) / ((now - previous[1]) * 1e6) * 100, 1)

    @staticmethod
    def memory_mb() -> float | None:
        current = read("memory.current") or read("memory/memory.usage_in_bytes")
        return round(int(current) / 2**20, 1) if current else None
