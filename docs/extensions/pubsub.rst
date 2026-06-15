Publish/Subscribe
~~~~~~~~~~~~~~~~~~

.. list-table::
   :align: left

   * - Compatibility
     - | CPython & MicroPython

   * - Required Microdot source files
     -  | `pubsub.py <https://github.com/miguelgrinberg/microdot/tree/main/src/microdot/pubsub.py>`_
        | `sse.py <https://github.com/miguelgrinberg/microdot/tree/main/src/microdot/sse.py>`_ and/or `websocket.py <https://github.com/miguelgrinberg/microdot/tree/main/src/microdot/websocket.py>`_

   * - Required external dependencies
     - | None

   * - Examples
     - | `chat.py <https://github.com/miguelgrinberg/microdot/blob/main/examples/pubsub/chat.py>`_

The publish/subscribe extension is a small, transport-agnostic message broker
that makes it easy to broadcast messages to many clients. It works equally well
with :func:`Server-Sent Events <microdot.sse.with_sse>` and
:func:`WebSocket <microdot.websocket.with_websocket>` connections, so the same
broker can feed both at the same time.

The broker organizes messages into named *channels*. A publisher sends a message
to a channel, and every client that is subscribed to that channel receives a
copy. Publishing to a channel that has no subscribers is not an error; the
message is simply delivered to nobody.

A single :class:`PubSub <microdot.pubsub.PubSub>` broker is normally created at
the application level and shared by all the routes that need it::

    from microdot import Microdot
    from microdot.pubsub import PubSub

    app = Microdot()
    pubsub = PubSub()

Broadcasting to clients
^^^^^^^^^^^^^^^^^^^^^^^^

The :meth:`stream() <microdot.pubsub.PubSub.stream>` helper removes most of the
boilerplate involved in feeding a connection from a channel. It subscribes to
one or more channels, forwards every message to the connection and cleans up the
subscription when the client disconnects. Because both the SSE and WebSocket
connection objects provide an asynchronous ``send()`` method, the same helper
works for either one::

    @app.route('/events')
    @with_sse
    async def events(request, sse):
        await pubsub.stream(sse, 'news')

    @app.route('/ws')
    @with_websocket
    async def ws(request, ws):
        await pubsub.stream(ws, 'news')

Since the WebSocket protocol can only carry strings or bytes, a ``serializer``
function can be given to encode structured messages, for example as JSON::

    import json

    @app.route('/ws')
    @with_websocket
    async def ws(request, ws):
        await pubsub.stream(ws, 'news', serializer=json.dumps)

Publishing messages
^^^^^^^^^^^^^^^^^^^^

Any part of the application can publish a message to a channel with the
:meth:`publish() <microdot.pubsub.PubSub.publish>` method, which returns the
number of subscribers the message was delivered to::

    @app.post('/announce')
    async def announce(request):
        await pubsub.publish('news', request.body.decode())
        return 'sent'

A common pattern is a chat room, where each client both publishes and receives
messages over the same WebSocket connection. The
:meth:`subscribe() <microdot.pubsub.PubSub.subscribe>` method returns a
:class:`Subscriber <microdot.pubsub.Subscriber>`, which is an asynchronous
iterator and asynchronous context manager::

    import asyncio

    @app.route('/chat')
    @with_websocket
    async def chat(request, ws):
        async with pubsub.subscribe('chat') as subscriber:
            async def send():
                async for message in subscriber:
                    await ws.send(message)

            sender = asyncio.create_task(send())
            try:
                while True:
                    message = await ws.receive()
                    await pubsub.publish('chat', message)
            finally:
                sender.cancel()

Using the subscriber as an ``async with`` context manager guarantees that the
subscription is removed from the broker when the connection ends, even if the
client disconnects abruptly. This prevents stale connections from accumulating
in memory over time.

Edge cases
^^^^^^^^^^

The broker is designed to behave well under common edge conditions:

- **No subscribers:** publishing to an empty channel is a no-op that returns
  ``0``.
- **Duplicate subscriptions:** subscribing the same subscriber to a channel it
  already belongs to has no effect, so each message is delivered only once.
- **Slow consumers:** each subscriber has its own message queue, and delivery
  never blocks the publisher. By passing a ``maxsize`` value when subscribing,
  the queue becomes bounded; when it is full, the oldest queued message is
  dropped to make room for the new one, so a slow or stalled consumer cannot
  exhaust memory::

      subscriber = pubsub.subscribe('news', maxsize=100)

  The number of messages that have been dropped for a subscriber is available
  in its ``dropped`` attribute.
