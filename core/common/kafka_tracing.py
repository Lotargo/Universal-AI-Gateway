from opentelemetry import trace
from opentelemetry.propagate import inject, extract
from typing import List, Tuple, MutableMapping

# Define a type alias for Kafka headers
KafkaHeaders = List[Tuple[str, bytes]]


def inject_trace_context(headers: KafkaHeaders = None) -> KafkaHeaders:
    """
    Injects the current OpenTelemetry trace context into Kafka message headers.
    """
    if headers is None:
        headers = []

    # Create a dictionary to pass to the inject function
    carrier: MutableMapping[str, str] = {}
    inject(carrier)

    # The inject function populates the carrier dictionary with keys like 'traceparent'
    # We need to encode these into the Kafka header format (list of tuples)
    for key, value in carrier.items():
        headers.append((key, value.encode("utf-8")))

    return headers


def extract_trace_context(headers: KafkaHeaders) -> trace.SpanContext:
    """
    Extracts an OpenTelemetry trace context from Kafka message headers.
    """
    # Create a dictionary from the Kafka headers for the extract function
    carrier = {key: value.decode("utf-8") for key, value in headers}

    # Extract the context
    return extract(carrier)
