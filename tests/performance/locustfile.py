from locust import HttpUser, task, between, constant, events, tag
import json
import uuid
import sys

# ==============================================================================
# MAGIC PROXY (UNIVERSAL AI GATEWAY) LOAD TEST SUITE
# ==============================================================================
#
# Scenarios:
# 1. StressUser: High RPS test for Infrastructure (Redis/Kafka) using a mocked LLM.
# 2. ReActUser: Simulation of Agent logic (State management, History).
# 3. SwitchoverUser: Hits Tier aliases to trigger Rotation/Fallback logic.
#
# Configuration:
#   The system MUST run with AUTH_ENABLED=True to stress MongoDB.
#   All users automatically register and authenticate on start.
#
# Usage:
#   MOCK_MODE=true AUTH_ENABLED=true locust -f tests/performance/locustfile.py --headless -u 10 -r 2 --run-time 30s --host http://localhost:8000
# ==============================================================================

class AuthenticatedUser(HttpUser):
    """
    Base user that handles automatic registration and token management.
    Ensures MongoDB is exercised during the load test.
    """
    abstract = True
    token = None
    wait_time = constant(0.5)

    def on_start(self):
        # Register a new user to generate a unique token and hit MongoDB
        username = f"load_user_{uuid.uuid4().hex[:8]}"

        # We use a context manager to ensure we catch failures in setup
        with self.client.post("/v1/auth/register", json={"username": username}, name="/v1/auth/register", catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("token")
                if self.token:
                    # Update global headers for this session
                    self.client.headers.update({"Authorization": f"Bearer {self.token}"})
                else:
                    response.failure("Registration succeeded but no token returned")
            else:
                response.failure(f"Registration failed: {response.status_code} - {response.text}")

class StressUser(AuthenticatedUser):
    """
    Simulates high-throughput traffic to the standard chat endpoint.
    Goal: Stress test the FastAPI server, Redis cache, and Event Loop.
    """
    wait_time = constant(0.5)

    @tag('stress')
    @task
    def chat_completion_mock(self):
        if not self.token:
            return # Skip if auth failed

        payload = {
            "model": "load_test_agent", # Renamed from mock_agent
            "messages": [{"role": "user", "content": "Stress test payload " * 5}],
            "stream": True
        }
        # We use stream=True to test the streaming infrastructure overhead
        with self.client.post("/v1/chat/completions", json=payload, catch_response=True, name="/v1/chat/completions (Stress)") as response:
            if response.status_code != 200:
                response.failure(f"Failed with status {response.status_code}: {response.text}")

class ReActUser(AuthenticatedUser):
    """
    Simulates Agent interactions which involve heavier server-side logic
    (Context construction, Pattern loading, Scratchpad management).
    """
    wait_time = between(2, 5)

    @tag('agent_reasoning')
    @task
    def agent_reasoning(self):
        if not self.token:
            return

        payload = {
            "model": "standard_agent", # Triggers StreamingManager
            "messages": [{"role": "user", "content": "Analyze this complexity."}],
            "stream": True
        }
        with self.client.post("/v1/chat/completions", json=payload, catch_response=True, name="/v1/chat/completions (Agent)") as response:
            if response.status_code != 200:
                response.failure(f"Agent failed: {response.status_code}")

class SwitchoverUser(AuthenticatedUser):
    """
    Simulates traffic to Tier aliases to test the Rotation Manager and Redis counters.
    """
    wait_time = between(1, 3)

    @tag('rotation')
    @task
    def rotation_request(self):
        if not self.token:
            return

        payload = {
            "model": "coding_agent", # Triggers rotation logic in chat.py
            "messages": [{"role": "user", "content": "Simple rotation test."}],
            "stream": True
        }
        self.client.post("/v1/chat/completions", json=payload, name="/v1/chat/completions (Rotation)")
