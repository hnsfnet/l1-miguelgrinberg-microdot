import asyncio
from microdot import Microdot, send_file
from microdot.websocket import with_websocket
from microdot.pubsub import PubSub

app = Microdot()
pubsub = PubSub()


@app.route('/')
async def index(request):
    return send_file('index.html')


@app.route('/ws/<channel>')
@with_websocket
async def ws(request, ws, channel):
    """Subscribe a WebSocket client to a channel.

    Messages published to the channel are forwarded to the client as JSON
    objects with ``channel`` and ``message`` fields.
    """
    await pubsub.websocket_handler(ws, channel)


@app.post('/publish/<channel>')
async def publish(request, channel):
    """Publish a message to a channel.

    The request body is treated as JSON and forwarded to all subscribers.
    """
    message = request.json
    count = await pubsub.publish(channel, message)
    return {'delivered': count}


app.run()
