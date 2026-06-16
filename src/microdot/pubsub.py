import asyncio

try:
    import orjson as json  # type: ignore[import-not-found]
except ImportError:
    import json


class PubSub:
    """A lightweight publish/subscribe broker for WebSocket and SSE.

    This class manages named channels and their subscribers. Messages
    published to a channel are delivered to all current subscribers via
    ``asyncio.Queue`` objects. Both SSE and WebSocket transports are
    supported through the :meth:`sse_response` and
    :meth:`websocket_handler` helper methods.

    Example::

        from microdot import Microdot
        from microdot.pubsub import PubSub
        from microdot.sse import with_sse
        from microdot.websocket import with_websocket

        app = Microdot()
        pubsub = PubSub()

        @app.route('/events/<channel>')
        async def events(request, channel):
            return pubsub.sse_response(request, channel)

        @app.route('/ws/<channel>')
        @with_websocket
        async def ws(request, ws, channel):
            await pubsub.websocket_handler(ws, channel)

        @app.post('/publish/<channel>')
        async def publish(request, channel):
            await pubsub.publish(channel, request.json)
            return {'status': 'ok'}
    """

    #: Maximum number of messages queued per subscriber. When a subscriber's
    #: queue is full (slow consumer), new messages are silently dropped for
    #: that subscriber. The default is 256.
    max_queue_size = 256

    def __init__(self):
        self._channels = {}

    def subscribe(self, channel):
        """Subscribe to a channel.

        :param channel: the channel name to subscribe to.
        :returns: an ``asyncio.Queue`` that will receive published messages.

        Each call returns a new queue, even for the same channel. Duplicate
        subscriptions by the same queue object are ignored.
        """
        if channel not in self._channels:
            self._channels[channel] = set()
        queue = asyncio.Queue(maxsize=self.max_queue_size)
        self._channels[channel].add(queue)
        return queue

    def unsubscribe(self, channel, queue):
        """Unsubscribe a queue from a channel.

        :param channel: the channel name.
        :param queue: the queue returned by :meth:`subscribe`.

        If the channel has no remaining subscribers, it is removed
        automatically. It is safe to call this method even if the queue
        is not subscribed to the channel.
        """
        if channel in self._channels:
            self._channels[channel].discard(queue)
            if not self._channels[channel]:
                del self._channels[channel]

    async def publish(self, channel, message):
        """Publish a message to all subscribers of a channel.

        :param channel: the channel name.
        :param message: the message to publish. Can be any value.

        Messages are delivered immediately to all subscriber queues via
        ``put_nowait``. If a subscriber's queue is full (slow consumer),
        the message is dropped for that subscriber. If no subscribers
        exist for the channel, this method is a no-op.

        :returns: the number of subscribers the message was delivered to.
        """
        if channel not in self._channels:
            return 0
        count = 0
        for queue in list(self._channels[channel]):
            try:
                queue.put_nowait(message)
                count += 1
            except asyncio.QueueFull:
                pass
        return count

    def channels(self):
        """Return the list of channels that have at least one subscriber."""
        return list(self._channels.keys())

    def subscriber_count(self, channel):
        """Return the number of subscribers for a channel."""
        return len(self._channels.get(channel, set()))

    def sse_response(self, request, channels, event_map=None):
        """Return an SSE response that streams messages from channels.

        :param request: the request object.
        :param channels: a channel name (string) or list of channel names to
                         subscribe to.
        :param event_map: an optional dict mapping channel names to SSE event
                          names. If not given, channel names are used as SSE
                          event names.

        This method is designed to be returned directly from a route handler::

            @app.route('/events/<channel>')
            async def events(request, channel):
                return pubsub.sse_response(request, channel)

        The SSE connection stays open until the client disconnects. Channel
        names are sent as the SSE ``event`` field so that the client can
        distinguish messages from different channels.
        """
        from microdot.sse import sse_response as _sse_response

        if isinstance(channels, str):
            channels = [channels]

        async def handler(request, sse):
            queues = {}
            forward_tasks = []
            try:
                for ch in channels:
                    queues[ch] = self.subscribe(ch)

                async def forward(ch, q):
                    while True:
                        msg = await q.get()
                        event_name = (event_map or {}).get(ch, ch)
                        await sse.send(msg, event=event_name)

                forward_tasks = [
                    asyncio.create_task(forward(ch, q))
                    for ch, q in queues.items()
                ]
                await asyncio.gather(*forward_tasks)
            except asyncio.CancelledError:
                pass
            finally:
                for t in forward_tasks:
                    t.cancel()
                for ch, q in queues.items():
                    self.unsubscribe(ch, q)

        return _sse_response(request, handler)

    async def websocket_handler(self, ws, channels):
        """Handle a WebSocket connection subscribed to channels.

        :param ws: the WebSocket object.
        :param channels: a channel name (string) or list of channel names to
                         subscribe to.

        Messages published to subscribed channels are forwarded to the
        WebSocket client as JSON objects with ``channel`` and ``message``
        fields::

            {"channel": "news", "message": {"headline": "Hello!"}}

        This method blocks until the client disconnects and is intended to
        be used inside a ``@with_websocket`` handler::

            @app.route('/ws/<channel>')
            @with_websocket
            async def ws(request, ws, channel):
                await pubsub.websocket_handler(ws, channel)
        """
        if isinstance(channels, str):
            channels = [channels]

        queues = {}
        tasks = []
        try:
            for ch in channels:
                queues[ch] = self.subscribe(ch)

            async def forward(ch, q):
                while True:
                    msg = await q.get()
                    await ws.send(
                        json.dumps({'channel': ch, 'message': msg})
                    )

            async def receive():
                while True:
                    await ws.receive()

            tasks = [
                asyncio.create_task(forward(ch, q))
                for ch, q in queues.items()
            ]
            tasks.append(asyncio.create_task(receive()))

            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            pass
        finally:
            for t in tasks:
                t.cancel()
            for ch, q in queues.items():
                self.unsubscribe(ch, q)
