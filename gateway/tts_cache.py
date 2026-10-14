"""有条数和总字节上限的 LRU，避免短回答挤占全部音频内存。"""
from collections import OrderedDict


class AudioCache(OrderedDict):
    def __init__(self, max_entries=32, max_bytes=4 * 1024 * 1024):
        super().__init__()
        self.max_entries = max_entries
        self.max_bytes = max_bytes

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __setitem__(self, key, value):
        if len(value) > self.max_bytes:
            return
        if key in self:
            super().__delitem__(key)
        while self and (len(self) >= self.max_entries or
                       sum(map(len, self.values())) + len(value) > self.max_bytes):
            self.popitem(last=False)
        super().__setitem__(key, value)

    def popitem(self, last=True):
        # 不让 OrderedDict 的底层 pop 路径触发会移动键的 __getitem__。
        if not self:
            raise KeyError('dictionary is empty')
        key = next(reversed(self)) if last else next(iter(self))
        value = super().__getitem__(key)
        super().__delitem__(key)
        return key, value
