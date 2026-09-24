class MemoryFilter:
    def is_meaningful(self, event):
        if event.event_type != "user_input":
            return False

        if not event.payload:
            return False

        text = event.payload.get("text", "").strip()

        if not text:
            return False

        return True

    def create_memory(self, event):
        return {
            "source": event.event_type,
            "timestamp": event.timestamp,
            "content": event.payload,
        }
