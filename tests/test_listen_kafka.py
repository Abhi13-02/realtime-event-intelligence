import json
from kafka import KafkaConsumer

# Make sure this matches your Kafka server address (usually localhost:9092 for local dev)
KAFKA_BROKER = "localhost:9092" 
TOPIC_NAME = "raw-articles"

def listen_to_queue():
    print(f"🎧 Listening to Kafka topic '{TOPIC_NAME}'...")
    print("Waiting for Celery to drop articles onto the belt...\n")
    
    # Initialize the consumer
    consumer = KafkaConsumer(
        TOPIC_NAME,
        bootstrap_servers=[KAFKA_BROKER],
        auto_offset_reset='latest', # Only listen for NEW messages from this moment on
        value_deserializer=lambda x: json.loads(x.decode('utf-8'))
    )

    try:
        # This creates an infinite loop, constantly watching the queue
        for message in consumer:
            article = message.value
            print("📦 NEW ARTICLE DETECTED ON KAFKA!")
            print(f"Headline: {article.get('headline')}")
            print(f"Source: {article.get('source_id')}")
            print("-" * 50)
    except KeyboardInterrupt:
        print("\n🛑 Stopped listening.")

if __name__ == "__main__":
    listen_to_queue()