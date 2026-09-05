"""Kafka messaging integration module."""
from backend.kafka.producer import KafkaProducerService, get_kafka_producer
from backend.kafka.consumer import KafkaConsumerService

__all__ = ["KafkaProducerService", "get_kafka_producer", "KafkaConsumerService"]
