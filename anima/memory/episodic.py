from anima.memory.memory_store import MemoryStore


class EpisodicMemory:
    """Read-oriented compatibility view over the Stage 1 SQLite MemoryStore."""

    def __init__(self, store):
        if not isinstance(store, MemoryStore):
            raise ValueError("EpisodicMemory requires a MemoryStore")

        self.store = store

    def load_memories(self):
        return self.store.list_memories()

    def count(self):
        return self.store.count()

    def last(self, limit=5):
        return self.store.last(limit)
