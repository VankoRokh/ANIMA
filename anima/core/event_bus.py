from datetime import datetime


class Event:
    def __init__(self, event_type, payload=None):
        self.event_type = event_type
        self.payload = payload
        self.timestamp = datetime.now().isoformat(timespec="seconds")

    def to_dict(self):
        return {
            "type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


class EventBus:
    def __init__(self):
        self.queue = []

    def emit(self, event_type, payload=None):
        event = Event(event_type, payload)
        self.queue.append(event)
        return event

    def has_events(self):
        return len(self.queue) > 0

    def next_event(self):
        if not self.queue:
            return None

        return self.queue.pop(0)
