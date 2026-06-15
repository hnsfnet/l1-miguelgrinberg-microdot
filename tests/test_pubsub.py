import asyncio
import json
import unittest
from microdot import Microdot
from microdot.sse import with_sse
from microdot.websocket import with_websocket
from microdot.pubsub import PubSub, Subscriber
from microdot.test_client import TestClient


class TestPubSub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if hasattr(asyncio, 'set_event_loop'):
            asyncio.set_event_loop(asyncio.new_event_loop())
        cls.loop = asyncio.get_event_loop()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def test_subscribe_and_publish(self):
        pubsub = PubSub()

        async def scenario():
            sub = pubsub.subscribe('news')
            count = await pubsub.publish('news', 'hello')
            message = await sub.__anext__()
            return count, message

        count, message = self._run(scenario())
        self.assertEqual(count, 1)
        self.assertEqual(message, 'hello')

    def test_broadcast_to_multiple_subscribers(self):
        pubsub = PubSub()

        async def scenario():
            sub1 = pubsub.subscribe('news')
            sub2 = pubsub.subscribe('news')
            count = await pubsub.publish('news', 'hello')
            return count, await sub1.__anext__(), await sub2.__anext__()

        count, m1, m2 = self._run(scenario())
        self.assertEqual(count, 2)
        self.assertEqual(m1, 'hello')
        self.assertEqual(m2, 'hello')

    def test_channel_isolation(self):
        pubsub = PubSub()

        async def scenario():
            sub_a = pubsub.subscribe('a')
            sub_b = pubsub.subscribe('b')
            await pubsub.publish('a', 'for-a')
            return sub_a.queue[:], sub_b.queue[:]

        queue_a, queue_b = self._run(scenario())
        self.assertEqual(queue_a, ['for-a'])
        self.assertEqual(queue_b, [])

    def test_subscriber_with_multiple_channels(self):
        pubsub = PubSub()

        async def scenario():
            sub = pubsub.subscribe('a', 'b')
            await pubsub.publish('a', 'from-a')
            await pubsub.publish('b', 'from-b')
            return await sub.__anext__(), await sub.__anext__()

        first, second = self._run(scenario())
        self.assertEqual([first, second], ['from-a', 'from-b'])

    def test_unsubscribe(self):
        pubsub = PubSub()

        async def scenario():
            sub = pubsub.subscribe('a')
            sub.unsubscribe('a')
            count = await pubsub.publish('a', 'hello')
            return count, sub.queue[:], 'a' in pubsub.subscribers

        count, queue, channel_present = self._run(scenario())
        self.assertEqual(count, 0)
        self.assertEqual(queue, [])
        self.assertFalse(channel_present)

    def test_duplicate_subscribe_is_idempotent(self):
        pubsub = PubSub()

        async def scenario():
            sub = pubsub.subscribe('a')
            sub.subscribe('a')
            sub.subscribe('a')
            count = await pubsub.publish('a', 'hello')
            return count, sub.channels, len(pubsub.subscribers['a'])

        count, channels, subscriber_count = self._run(scenario())
        self.assertEqual(count, 1)
        self.assertEqual(channels, {'a'})
        self.assertEqual(subscriber_count, 1)

    def test_publish_with_no_subscribers(self):
        pubsub = PubSub()

        async def scenario():
            return await pubsub.publish('ghost', 'nobody is listening')

        self.assertEqual(self._run(scenario()), 0)

    def test_close_cleans_up_subscriptions(self):
        pubsub = PubSub()

        async def scenario():
            sub = pubsub.subscribe('a', 'b')
            self.assertIn('a', pubsub.subscribers)
            self.assertIn('b', pubsub.subscribers)
            sub.close()
            return sub.closed, sub.channels, pubsub.subscribers

        closed, channels, subscribers = self._run(scenario())
        self.assertTrue(closed)
        self.assertEqual(channels, set())
        self.assertEqual(subscribers, {})

    def test_closed_subscriber_drains_then_stops(self):
        pubsub = PubSub()

        async def scenario():
            sub = pubsub.subscribe('a')
            await pubsub.publish('a', 'queued')
            sub.close()
            received = []
            async for message in sub:
                received.append(message)
            return received

        # messages already queued are still delivered, then iteration ends
        self.assertEqual(self._run(scenario()), ['queued'])

    def test_slow_consumer_drops_oldest(self):
        pubsub = PubSub()

        async def scenario():
            sub = pubsub.subscribe('a', maxsize=2)
            await pubsub.publish('a', 'm0')
            await pubsub.publish('a', 'm1')
            await pubsub.publish('a', 'm2')
            return sub.queue[:], sub.dropped

        queue, dropped = self._run(scenario())
        self.assertEqual(queue, ['m1', 'm2'])
        self.assertEqual(dropped, 1)

    def test_context_manager_cleanup(self):
        pubsub = PubSub()

        async def scenario():
            async with pubsub.subscribe('a') as sub:
                self.assertIn('a', pubsub.subscribers)
            return sub.closed, pubsub.subscribers

        closed, subscribers = self._run(scenario())
        self.assertTrue(closed)
        self.assertEqual(subscribers, {})

    def test_subscribe_after_close_has_no_effect(self):
        pubsub = PubSub()

        async def scenario():
            sub = Subscriber(pubsub)
            sub.close()
            sub.subscribe('a')
            return sub.channels, pubsub.subscribers

        channels, subscribers = self._run(scenario())
        self.assertEqual(channels, set())
        self.assertEqual(subscribers, {})

    def test_sse_broadcast(self):
        app = Microdot()
        pubsub = PubSub()

        @app.route('/sse')
        @with_sse
        async def events(request, sse):
            count = 0
            async with pubsub.subscribe('news') as subscriber:
                async for message in subscriber:
                    await sse.send(message)
                    count += 1
                    if count >= 3:
                        break

        client = TestClient(app)

        async def scenario():
            async def publisher():
                while 'news' not in pubsub.subscribers:
                    await asyncio.sleep(0)
                for i in range(3):
                    await pubsub.publish('news', 'msg{}'.format(i))
                    await asyncio.sleep(0)

            pub_task = asyncio.create_task(publisher())
            response = await client.get('/sse')
            await pub_task
            return response

        response = self._run(scenario())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'text/event-stream')
        self.assertEqual(len(response.events), 3)
        self.assertEqual(response.events[0]['data'], b'msg0')
        self.assertEqual(response.events[1]['data'], b'msg1')
        self.assertEqual(response.events[2]['data'], b'msg2')
        # the subscriber must be cleaned up after the client disconnects
        self.assertEqual(pubsub.subscribers, {})

    def test_sse_broadcast_with_stream_helper(self):
        app = Microdot()
        pubsub = PubSub()

        @app.route('/sse')
        @with_sse
        async def events(request, sse):
            # the stream() helper loops forever, so cap the connection with a
            # subscriber that the test closes from the publisher side
            await pubsub.stream(sse, 'news')

        client = TestClient(app)

        async def scenario():
            async def publisher():
                while 'news' not in pubsub.subscribers:
                    await asyncio.sleep(0)
                for i in range(3):
                    await pubsub.publish('news', 'msg{}'.format(i))
                    await asyncio.sleep(0)
                # close the subscriber to end the stream and the connection
                for sub in list(pubsub.subscribers.get('news', ())):
                    sub.close()

            pub_task = asyncio.create_task(publisher())
            response = await client.get('/sse')
            await pub_task
            return response

        response = self._run(scenario())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.events), 3)
        self.assertEqual(response.events[0]['data'], b'msg0')
        self.assertEqual(pubsub.subscribers, {})

    def test_websocket_broadcast(self):
        app = Microdot()
        pubsub = PubSub()

        @app.route('/ws')
        @with_websocket
        async def feed(request, ws):
            await ws.receive()  # wait for the client to say hello
            count = 0
            async with pubsub.subscribe('news') as subscriber:
                async for message in subscriber:
                    await ws.send(message)
                    count += 1
                    if count >= 3:
                        break

        results = []

        def ws_client():
            # every yielded value is encoded by the test client into a frame,
            # so each yield must produce a sendable value even though this
            # send-only endpoint never reads them back
            data = yield 'start'
            results.append(data)
            data = yield 'ack'
            results.append(data)
            data = yield 'ack'
            results.append(data)
            yield 'ack'  # keep the client alive after the server stops sending

        client = TestClient(app)

        async def scenario():
            async def publisher():
                while 'news' not in pubsub.subscribers:
                    await asyncio.sleep(0)
                for i in range(3):
                    await pubsub.publish('news', 'msg{}'.format(i))
                    await asyncio.sleep(0)

            pub_task = asyncio.create_task(publisher())
            response = await client.websocket('/ws', ws_client)
            await pub_task
            return response

        self._run(scenario())
        self.assertEqual(results, ['msg0', 'msg1', 'msg2'])
        # the subscriber must be cleaned up after the connection ends
        self.assertEqual(pubsub.subscribers, {})

    def test_websocket_channel_isolation(self):
        app = Microdot()
        pubsub = PubSub()

        @app.route('/ws')
        @with_websocket
        async def feed(request, ws):
            channel = await ws.receive()
            async with pubsub.subscribe(channel) as subscriber:
                async for message in subscriber:
                    await ws.send(message)
                    break

        results = []

        def make_client(channel):
            def ws_client():
                data = yield channel
                results.append((channel, data))
                yield 'ack'  # keep alive after the single message
            return ws_client

        client = TestClient(app)

        async def scenario():
            async def publisher():
                while 'b' not in pubsub.subscribers:
                    await asyncio.sleep(0)
                # only channel 'b' has a subscriber here; 'a' has none
                await pubsub.publish('a', 'for-a')
                await pubsub.publish('b', 'for-b')
                await asyncio.sleep(0)

            pub_task = asyncio.create_task(publisher())
            await client.websocket('/ws', make_client('b'))
            await pub_task

        self._run(scenario())
        self.assertEqual(results, [('b', 'for-b')])
        self.assertEqual(pubsub.subscribers, {})

    def test_close_one_subscriber_keeps_channel(self):
        pubsub = PubSub()

        async def scenario():
            sub1 = pubsub.subscribe('room')
            sub2 = pubsub.subscribe('room')
            sub1.close()
            # the channel survives because sub2 is still subscribed
            count = await pubsub.publish('room', 'hi')
            return count, 'room' in pubsub.subscribers, await sub2.__anext__()

        count, channel_present, message = self._run(scenario())
        self.assertEqual(count, 1)
        self.assertTrue(channel_present)
        self.assertEqual(message, 'hi')

    def test_stream_helper_with_serializer(self):
        # the stream() helper can serialize messages on their way out, which is
        # what a WebSocket endpoint needs to broadcast dictionaries as JSON
        pubsub = PubSub()

        class FakeConnection:
            def __init__(self, stop_after):
                self.sent = []
                self.stop_after = stop_after

            async def send(self, message):
                self.sent.append(message)
                if len(self.sent) >= self.stop_after:
                    # simulate the client disconnecting
                    raise OSError('client disconnected')

        async def scenario():
            conn = FakeConnection(2)
            task = asyncio.create_task(
                pubsub.stream(conn, 'news', serializer=json.dumps))
            while 'news' not in pubsub.subscribers:
                await asyncio.sleep(0)
            await pubsub.publish('news', {'a': 1})
            await pubsub.publish('news', {'b': 2})
            try:
                await task
            except OSError:
                pass
            return conn.sent, pubsub.subscribers

        sent, subscribers = self._run(scenario())
        self.assertEqual(sent, ['{"a": 1}', '{"b": 2}'])
        # the subscription is cleaned up even though the client disconnected
        self.assertEqual(subscribers, {})


if __name__ == '__main__':
    unittest.main()
