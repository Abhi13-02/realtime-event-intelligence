from app.pipeline.interfaces import EventBusInterface
from typing import List
from uuid import UUID

class MockKafkaAdapter(EventBusInterface):
    """
    A placeholder adapter for the Message Bus Interface. 
    Logs published messages without requiring a live Kafka broker.
    Can be seamlessly swapped with a real Kafka producer.
    """
    def publish_matched_article(self, article_id: UUID, topic_id: UUID, relevance_score: float, user_ids: List[UUID]) -> None:
        print(f"[EVENT BUS] Publishing -> Article: {article_id} | Topic: {topic_id} | Score: {relevance_score:.3f} | Users Count: {len(user_ids)}")
