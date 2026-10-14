"""有条数和总字节上限的 LRU，避免短回答挤占全部音频内存。"""
from collections import OrderedDict


class AudioCache(OrderedDict):
    def __init__(self, max_entries=32, max_bytes=4 * 1024 * 1024):
        super().__init__()
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.current_bytes = 0

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
        value = bytes(value)
        if len(value) > self.max_bytes:
            return
        if key in self:
            del self[key]
        while self and (len(self) >= self.max_entries or
                       self.current_bytes + len(value) > self.max_bytes):
            self.popitem(last=False)
        super().__setitem__(key, value)
        self.current_bytes += len(value)

    def __delitem__(self, key):
        value = super().__getitem__(key)
        super().__delitem__(key)
        self.current_bytes -= len(value)

    def clear(self):
        super().clear()
        self.current_bytes = 0

    def pop(self, key, *default):
        if len(default) > 1:
            raise TypeError('pop expected at most 2 arguments')
        if key not in self:
            if default:
                return default[0]
            raise KeyError(key)
        value = super().__getitem__(key)
        del self[key]
        return value

    def popitem(self, last=True):
        # 不让 OrderedDict 的底层 pop 路径触发会移动键的 __getitem__。
        if not self:
            raise KeyError('dictionary is empty')
        key = next(reversed(self)) if last else next(iter(self))
        value = super().__getitem__(key)
        del self[key]
        return key, value
