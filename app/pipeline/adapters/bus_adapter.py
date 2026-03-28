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
        print(f"\n[KAFKA EVENT] Publishing Article to Service...")
        print(f"   -> Article_ID : {article_id}")
        print(f"   -> Topic_ID   : {topic_id}")
        print(f"   -> Score      : {relevance_score:.3f}")
        for u in user_ids:
            print(f"   -> To User_ID : {u}")
