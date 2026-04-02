from app.pipeline.interfaces import EventBusInterface
from typing import List
from uuid import UUID
import json
import logging
from kafka import KafkaProducer

logger = logging.getLogger(__name__)

class MockKafkaAdapter(EventBusInterface):
    """
    A placeholder adapter for the Message Bus Interface. 
    Logs published messages without requiring a live Kafka broker.
    Can be seamlessly swapped with a real Kafka producer.
    """
    def publish_matched_article(self, article_id: UUID, topic_id: UUID, relevance_score: float, user_id: UUID) -> None:
        print(f"\n[KAFKA EVENT] Publishing Article to Service...")
        print(f"   -> Article_ID : {article_id}")
        print(f"   -> Topic_ID   : {topic_id}")
        print(f"   -> Score      : {relevance_score:.3f}")
        print(f"   -> To User_ID : {user_id}")


class KafkaAdapter(EventBusInterface):
    """
    Real Kafka adapter for publishing matched articles to the 'matched-articles' topic.
    Used by the pipeline to broadcast matching articles for the Alert Service.
    """
    def __init__(self, bootstrap_servers: str = "localhost:9092", topic: str = "matched-articles"):
        self.topic = topic
        try:
            self.producer = KafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            logger.info(f"Connected to Kafka at {bootstrap_servers}")
        except Exception as e:
            logger.error(f"Failed to connect to Kafka at {bootstrap_servers}: {e}")
            raise
        
    def publish_matched_article(self, article_id: UUID, topic_id: UUID, relevance_score: float, user_id: UUID) -> None:
        payload = {
            "article_id": str(article_id),
            "topic_id": str(topic_id),
            "relevance_score": relevance_score,
            "user_id": str(user_id)
        }
        self.producer.send(self.topic, payload)
        self.producer.flush()
