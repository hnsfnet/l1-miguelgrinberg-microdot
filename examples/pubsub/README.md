Pub/Sub Example
===============

This example shows how to use the `microdot.pubsub` mini-framework to broadcast
messages to many clients over a named channel. The same `PubSub` broker feeds
both a Server-Sent Events endpoint and a WebSocket endpoint, so a single message
reaches every connected client regardless of the transport it uses.

Running the example
-------------------

    python chat.py

Then open http://localhost:5000 in two browser tabs. Type a message in one tab
and it appears in both, received over the WebSocket *and* over SSE.

You can also publish a message from the command line:

    curl -d "message=hello" http://localhost:5000/publish
