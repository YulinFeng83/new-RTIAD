"""
Azure Event Hub producer — fire-and-forget event publishing.

Configurable on/off via `event_hub.enabled` in config. When disabled,
events are logged to the console only (no Azure dependency needed).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from typing import Any, Optional

from src.config import EventHubConfig

logger = logging.getLogger(__name__)


class EventHubProducer:
    """
    Publishes events to Azure Event Hub in batches.

    When `enabled=False`, events are logged locally instead. This allows
    full local testing without Azure credentials.
    """

    def __init__(self, config: EventHubConfig):
        self._config = config
        self._enabled = config.enabled
        self._buffer: deque[dict[str, Any]] = deque()
        self._lock = threading.Lock()
        self._producer = None
        self._flush_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        if self._enabled:
            try:
                from azure.eventhub import EventHubProducerClient
                self._producer = EventHubProducerClient.from_connection_string(
                    conn_str=self._config.connection_string,
                    eventhub_name=self._config.event_hub_name,
                )
                logger.info("Azure Event Hub producer connected: %s", self._config.event_hub_name)
            except Exception:
                logger.exception("Failed to connect to Azure Event Hub — events will be logged locally")
                self._enabled = False
        else:
            logger.info("Event Hub disabled — events will be logged locally only")

        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._flush_thread:
            self._flush_thread.join(timeout=5)
        self._flush_pending()
        if self._producer:
            try:
                self._producer.close()
            except Exception:
                pass

    def send(self, event: dict[str, Any]) -> None:
        """Queue an event for batched sending."""
        with self._lock:
            self._buffer.append(event)

    def _flush_loop(self) -> None:
        while self._running:
            time.sleep(self._config.send_interval_seconds)
            self._flush_pending()

    def _flush_pending(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            batch = list(self._buffer)
            self._buffer.clear()

        if self._enabled and self._producer:
            self._send_to_eventhub(batch)
        else:
            for event in batch:
                logger.info("[Event] %s", json.dumps(event, default=str))

    def _send_to_eventhub(self, events: list[dict[str, Any]]) -> None:
        try:
            from azure.eventhub import EventData
            event_batch = self._producer.create_batch()

            for event in events:
                data = EventData(json.dumps(event, default=str))
                try:
                    event_batch.add(data)
                except ValueError:
                    self._producer.send_batch(event_batch)
                    event_batch = self._producer.create_batch()
                    event_batch.add(data)

            self._producer.send_batch(event_batch)
            logger.debug("Sent %d events to Event Hub", len(events))

        except Exception:
            logger.exception("Failed to send batch to Event Hub — %d events lost", len(events))

    def on_config_change(self, config: EventHubConfig) -> None:
        if config.enabled != self._enabled:
            logger.info("Event Hub enabled changed: %s → %s", self._enabled, config.enabled)
            self._config = config
            if config.enabled and not self._enabled:
                self._enabled = True
                self.start()
            elif not config.enabled:
                self._enabled = False
