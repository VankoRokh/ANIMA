class MemoryFilter:
    """Temporary Stage 0/D1 selector until Memory Processor replaces it."""

    def is_meaningful(self, event):
        if event.event_type != "conversation.user":
            return False

        if not event.payload:
            return False

        text = event.payload.get("text", "").strip()

        if not text:
            return False

        return True

    def create_memory(self, event):
        return {
            "type": "episodic",
            "domain": "user",
            "status": "open",
            "content": event.payload["text"],
            "importance": 1,
            "created_at": event.timestamp,
            "source_event_id": event.event_id,
        }
