class ProvenanceResolver:
    """Resolve Stage 1 provenance from SQLite links back to raw Events."""

    def __init__(self, memory_store, link_store, event_log):
        self.memory_store = memory_store
        self.link_store = link_store
        self.event_log = event_log

    def memory(self, memory_id):
        memory = self.memory_store.get_memory(memory_id)
        if memory is None:
            raise ValueError(f"Unknown memory: {memory_id}")

        event_index = self._event_index()
        events = self._events_for_memory(memory_id, event_index)

        return {
            "memory": memory,
            "events": events,
        }

    def relation(self, relation_id):
        relation = self.link_store.get_relation(relation_id)
        if relation is None:
            raise ValueError(f"Unknown relation: {relation_id}")

        event_index = self._event_index()
        source_memory_id = relation["source_memory_id"]

        return {
            "relation": relation,
            "source_memory": self.memory_store.get_memory(
                source_memory_id
            ),
            "events": self._events_for_memory(
                source_memory_id,
                event_index,
            ),
        }

    def knowledge(self, knowledge_id):
        knowledge = self.link_store.get_knowledge(knowledge_id)
        if knowledge is None:
            raise ValueError(f"Unknown knowledge: {knowledge_id}")

        relations = self.link_store.relations_for(
            "knowledge",
            knowledge_id,
            direction="incoming",
            relation_types={"supports", "contradicts"},
        )
        event_index = self._event_index()
        sources = []

        for relation in relations:
            source_memory_id = relation["source_memory_id"]
            sources.append(
                {
                    "relation": relation,
                    "source_memory": self.memory_store.get_memory(
                        source_memory_id
                    ),
                    "events": self._events_for_memory(
                        source_memory_id,
                        event_index,
                    ),
                }
            )

        return {
            "knowledge": knowledge,
            "sources": sources,
        }

    def entity(self, entity_id):
        entity = self.link_store.get_entity(entity_id)
        if entity is None:
            raise ValueError(f"Unknown entity: {entity_id}")

        relations = self.link_store.relations_for(
            "entity",
            entity_id,
            direction="incoming",
            relation_types={"about"},
        )
        event_index = self._event_index()
        sources = []
        seen_memory_ids = set()

        for relation in relations:
            source_memory_id = relation["source_memory_id"]

            if source_memory_id in seen_memory_ids:
                continue

            seen_memory_ids.add(source_memory_id)
            sources.append(
                {
                    "relation": relation,
                    "source_memory": self.memory_store.get_memory(
                        source_memory_id
                    ),
                    "events": self._events_for_memory(
                        source_memory_id,
                        event_index,
                    ),
                }
            )

        return {
            "entity": entity,
            "sources": sources,
        }

    def _event_index(self):
        return {
            event["id"]: event
            for event in self.event_log.load_events()
        }

    def _events_for_memory(self, memory_id, event_index):
        event_ids = self.memory_store.source_events(memory_id)
        events = []

        for event_id in event_ids:
            event = event_index.get(event_id)

            if event is None:
                raise ValueError(
                    f"Missing source event {event_id} for memory {memory_id}"
                )

            events.append(event)

        return events
