import asyncio
import json
import os
import signal
import sys
from aiokafka import AIOKafkaConsumer

# Configuration
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:29092")
TOPIC = "agent_audit_events"
GROUP_ID = "load_test_verifier"

stop_event = asyncio.Event()

def signal_handler(sig, frame):
    print("\n[Monitor] Stop signal received. Shutting down...")
    stop_event.set()

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

async def monitor():
    print(f"[Monitor] Connecting to Kafka at {KAFKA_BROKER}...")
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id=GROUP_ID,
        auto_offset_reset="latest", # We only care about new messages during the test
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )

    try:
        await consumer.start()
        print(f"[Monitor] Connected. Listening to topic '{TOPIC}'...")

        count = 0
        start_time = asyncio.get_running_loop().time()

        while not stop_event.is_set():
            try:
                # Poll for messages with a timeout to check stop_event
                msg_set = await consumer.getmany(timeout_ms=1000, max_records=100)

                for tp, messages in msg_set.items():
                    for msg in messages:
                        count += 1
                        # Optional: Validate payload structure
                        # payload = msg.value
                        # if "session_id" not in payload: ...

                current_time = asyncio.get_running_loop().time()
                elapsed = current_time - start_time
                if elapsed > 0 and int(elapsed) % 5 == 0:
                     print(f"[Monitor] Received {count} messages so far ({count / elapsed:.1f} msg/s)...")

            except Exception as e:
                print(f"[Monitor] Error during consumption: {e}")
                # Don't crash, just retry
                await asyncio.sleep(1)

    finally:
        await consumer.stop()
        print(f"[Monitor] Stopped. Total messages received: {count}")

if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except KeyboardInterrupt:
        pass
