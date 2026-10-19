"""Identify anonymous SDK invocations without sharing the constant 'tool' ID."""
import uuid


class ToolIdentityRegistry:
    def __init__(self):
        self.active = {}

    def start(self, local_id, name):
        key = local_id or f'anonymous-{uuid.uuid4()}'
        self.active[key] = name
        return key

    def finish(self, local_id, name):
        if local_id:
            self.active.pop(local_id, None)
            return local_id
        matches = [key for key, value in self.active.items() if value == name]
        if len(matches) != 1:
            raise ValueError('Cannot correlate anonymous SDK tool result safely')
        key = matches[0]
        del self.active[key]
        return key
