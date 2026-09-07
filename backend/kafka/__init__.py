"""Kafka messaging integration module."""
from backend.kafka.consumer import KafkaConsumerService
from backend.kafka.clustering_consumer import KafkaBatchClusteringConsumer

__all__ = ["KafkaConsumerService", "KafkaBatchClusteringConsumer"]
