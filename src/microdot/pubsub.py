import asyncio


class Subscriber:
    """A subscriber to one or more pub/sub channels.

    Instances of this class are created by :meth:`PubSub.subscribe`. A
    subscriber holds an internal queue of messages that have been published to
    any of the channels it is subscribed to. It is an asynchronous iterator, so
    the most common way to consume messages is to iterate over it::

        async with pubsub.subscribe('news') as subscriber:
            async for message in subscriber:
                await sse.send(message)

    The ``async with`` block ensures that the subscriber is unsubscribed from
    all of its channels when the connection ends, even if the client
    disconnects abruptly.

    :param pubsub: the :class:`PubSub` broker this subscriber belongs to.
    :param maxsize: the maximum number of undelivered messages to keep queued
                    for this subscriber. When the limit is reached and a new
                    message arrives, the oldest queued message is dropped to
                    make room for it. This protects the application against
                    slow or stalled consumers that would otherwise make the
                    queue grow without bound. The default is ``0``, which means
                    the queue is unbounded.
    """
    def __init__(self, pubsub, maxsize=0):
        self.pubsub = pubsub
        self.maxsize = maxsize
        self.channels = set()
        self.queue = []
        self.event = asyncio.Event()
        self.closed = False
        #: The number of messages that have been dropped for this subscriber
        #: because its queue was full. Useful for diagnosing slow consumers.
        self.dropped = 0

    def subscribe(self, channel):
        """Add a channel to this subscriber.

        :param channel: the name of the channel to subscribe to.

        Subscribing to a channel that the subscriber is already subscribed to
        has no effect, so it is safe to call this method repeatedly.
        """
        if not self.closed and channel not in self.channels:
            self.channels.add(channel)
            self.pubsub._add(channel, self)

    def unsubscribe(self, channel):
        """Remove a channel from this subscriber.

        :param channel: the name of the channel to unsubscribe from.

        Unsubscribing from a channel that the subscriber is not subscribed to
        has no effect.
        """
        if channel in self.channels:
            self.channels.discard(channel)
            self.pubsub._remove(channel, self)

    def close(self):
        """Unsubscribe from all channels and stop the iterator.

        After this method is called the subscriber no longer receives messages
        and any active iteration over it ends. This is called automatically
        when the subscriber is used as an asynchronous context manager.
        """
        if not self.closed:
            self.closed = True
            for channel in list(self.channels):
                self.unsubscribe(channel)
            # wake up a possible pending iteration so that it can stop
            self.event.set()

    def _deliver(self, message):
        # this is called by the broker to enqueue a message for this
        # subscriber. It never blocks: if the queue is full the oldest message
        # is discarded so that a slow consumer cannot make the producer wait or
        # exhaust memory.
        if self.closed:  # pragma: no cover
            return
        if self.maxsize and len(self.queue) >= self.maxsize:
            self.queue.pop(0)
            self.dropped += 1
        self.queue.append(message)
        self.event.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            if self.queue:
                return self.queue.pop(0)
            if self.closed:
                raise StopAsyncIteration
            await self.event.wait()
            self.event.clear()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.close()


class PubSub:
    """A minimal publish/subscribe message broker.

    This object keeps track of channels and their subscribers and routes
    published messages to the right consumers. The same broker can be used to
    feed both Server-Sent Events and WebSocket connections, since both only
    require a way to push messages to a client.

    A single broker instance is normally created at the application level and
    shared by all the routes that need it::

        from microdot import Microdot
        from microdot.pubsub import PubSub

        app = Microdot()
        pubsub = PubSub()
    """
    def __init__(self):
        #: A mapping of channel name to the set of subscribers of that channel.
        self.subscribers = {}

    def subscribe(self, *channels, **kwargs):
        """Create a subscriber attached to the given channels.

        :param channels: one or more channel names to subscribe to. If no
                         channels are given, an empty subscriber is returned
                         and channels can be added later with
                         :meth:`Subscriber.subscribe`.
        :param maxsize: the maximum number of undelivered messages to keep
                        queued for the subscriber. See :class:`Subscriber` for
                        details. The default is ``0`` (unbounded).

        The returned :class:`Subscriber` is an asynchronous iterator and
        asynchronous context manager, so the recommended usage is::

            async with pubsub.subscribe('news') as subscriber:
                async for message in subscriber:
                    await connection.send(message)
        """
        maxsize = kwargs.get('maxsize', 0)
        subscriber = Subscriber(self, maxsize=maxsize)
        for channel in channels:
            subscriber.subscribe(channel)
        return subscriber

    async def publish(self, channel, message):
        """Publish a message to a channel.

        :param channel: the name of the channel to publish to.
        :param message: the message to deliver to all the subscribers of the
                        channel. It can be any object and is passed unchanged
                        to each subscriber.

        Returns the number of subscribers the message was delivered to.
        Publishing to a channel that has no subscribers is not an error and
        simply delivers the message to nobody.
        """
        count = 0
        # iterate over a copy of the subscriber set so that the original can be
        # safely mutated (for example if a subscriber closes) while delivering
        for subscriber in list(self.subscribers.get(channel, ())):
            subscriber._deliver(message)
            count += 1
        return count

    async def stream(self, connection, *channels, **kwargs):
        """Forward every message published to the given channels to a client.

        :param connection: the connection object to send messages through. Any
                           object with an asynchronous ``send(message)`` method
                           works, which includes both the ``sse`` object from
                           :func:`microdot.sse.with_sse` and the ``ws`` object
                           from :func:`microdot.websocket.with_websocket`.
        :param channels: one or more channel names to subscribe to.
        :param serializer: an optional function that is applied to each message
                           before it is sent. This is useful, for example, to
                           encode messages as JSON for WebSocket connections.
        :param maxsize: the maximum number of undelivered messages to keep
                        queued. See :class:`Subscriber` for details.

        This is a convenience helper that removes most of the boilerplate
        needed to feed a connection from a channel. A complete broadcast
        endpoint can be written as::

            @app.route('/events')
            @with_sse
            async def events(request, sse):
                await pubsub.stream(sse, 'news')

        The helper takes care of subscribing, forwarding messages and cleaning
        up the subscription when the client disconnects. It runs until the
        connection is closed.
        """
        serializer = kwargs.get('serializer')
        maxsize = kwargs.get('maxsize', 0)
        async with self.subscribe(*channels, maxsize=maxsize) as subscriber:
            async for message in subscriber:
                if serializer is not None:
                    message = serializer(message)
                await connection.send(message)

    def _add(self, channel, subscriber):
        if channel not in self.subscribers:
            self.subscribers[channel] = set()
        self.subscribers[channel].add(subscriber)

    def _remove(self, channel, subscriber):
        subscribers = self.subscribers.get(channel)
        if subscribers is not None:
            subscribers.discard(subscriber)
            # drop the channel entirely once it has no subscribers left, so
            # that abandoned channels do not accumulate in memory
            if not subscribers:
                del self.subscribers[channel]
