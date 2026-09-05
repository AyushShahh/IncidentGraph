"""Production Kafka producer package for streaming service logs."""
from shared.kafka.producer import KafkaLogProducer, get_shared_kafka_producer

# Backwards compatibility alias
GenericKafkaLogProducer = KafkaLogProducer

__all__ = ["KafkaLogProducer", "GenericKafkaLogProducer", "get_shared_kafka_producer"]
