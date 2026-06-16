# Microdot Pub/Sub Example

This example demonstrates the publish/subscribe mini-framework for WebSocket
and SSE.

## Running

```bash
pip install microdot
python chat.py
```

Then open `http://localhost:5000` in a web browser.

## How it works

The application exposes three endpoints:

- `GET /` — Serves the chat UI.
- `WS /ws/<channel>` — Subscribes a WebSocket client to a named channel.
  Messages published to the channel are forwarded to all connected clients
  as JSON: `{"channel": "...", "message": ...}`.
- `POST /publish/<channel>` — Publishes a JSON message to all subscribers
  of the given channel. Returns `{"delivered": N}`.

Open two or more browser tabs, choose a channel name, and send messages to
see them broadcast to all subscribers of that channel.

## Using PubSub in your own app

```python
from microdot import Microdot
from microdot.websocket import with_websocket
from microdot.pubsub import PubSub

app = Microdot()
pubsub = PubSub()

# Subscribe a WebSocket to a channel
@app.route('/ws/<channel>')
@with_websocket
async def ws(request, ws, channel):
    await pubsub.websocket_handler(ws, channel)

# Subscribe an SSE client to a channel
@app.route('/events/<channel>')
async def events(request, channel):
    return pubsub.sse_response(request, channel)

# Publish from any route handler
@app.post('/notify')
async def notify(request):
    await pubsub.publish('alerts', {'text': 'Server restarting!'})
    return 'ok'
```
