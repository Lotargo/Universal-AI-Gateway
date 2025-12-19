import os
import sys
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource


def setup_tracing(service_name="UniversalAIGateway"):
    """
    Configures OpenTelemetry tracing for the application.

    Modes:
    1. ENABLE_CONSOLE_TRACING=true -> Prints traces to stdout (cluttered).
    2. ENABLE_FILE_TRACING=true -> Prints traces to 'traces.json' file (cleaner console).
    3. Default -> Tracing enabled but no exporter (silent).
    """
    # Create a Resource to identify the service
    resource = Resource(attributes={"service.name": service_name})

    # Create a TracerProvider
    provider = TracerProvider(resource=resource)

    # Mode 1: Console Tracing (Debugging)
    if os.getenv("ENABLE_CONSOLE_TRACING", "false").lower() == "true":
        console_exporter = ConsoleSpanExporter()
        span_processor = BatchSpanProcessor(console_exporter)
        provider.add_span_processor(span_processor)

    # Mode 2: File Tracing (Separated Output)
    elif os.getenv("ENABLE_FILE_TRACING", "false").lower() == "true":
        # We use ConsoleSpanExporter but redirect the stream to a file
        try:
            trace_file = open("traces.json", "a")
            file_exporter = ConsoleSpanExporter(out=trace_file)
            span_processor = BatchSpanProcessor(file_exporter)
            provider.add_span_processor(span_processor)
        except Exception as e:
            print(f"Failed to setup file tracing: {e}", file=sys.stderr)

    # Set the global TracerProvider
    trace.set_tracer_provider(provider)

    # Return a tracer instance
    return trace.get_tracer(__name__)
