import json
import socketserver
import threading
import unittest

from ring.apps.vpet.bridge import VPetSession, ringo_messages, send_command


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            request = json.loads(raw)
            self.server.received.append(request)
            self.wfile.write((json.dumps({"command": request["command"], "ok": True,
                                           "error": None}) + "\n").encode())


class RingoHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.server.received.append(json.loads(self.rfile.readline()))
        for payload in ({"type": "hello", "version": 1},
                        {"type": "imu", "acc": [0, 0, 9.8], "gyr": [0, 0, 0]}):
            self.wfile.write((json.dumps(payload) + "\n").encode())


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.server.received = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_manual_command_and_move_share_protocol(self):
        address = self.server.server_address
        self.assertTrue(send_command("pet", address=address)["ok"])
        with VPetSession(address) as session:
            for command in ("MOVE_START", "MOVE_DELTA", "MOVE_END"):
                self.assertTrue(session.send(command, dx=12, dy=-4)["ok"])
        self.assertEqual([r["command"] for r in self.server.received],
                         ["PET", "MOVE_START", "MOVE_DELTA", "MOVE_END"])
        self.assertEqual(self.server.received[2]["dx"], 12)

    def test_reject_large_move(self):
        with VPetSession(self.server.server_address) as session:
            with self.assertRaises(ValueError):
                session.send("MOVE_DELTA", dx=81)
            with self.assertRaises(ValueError):
                session.send("MOVE_DELTA", dx=float("nan"))
        self.assertEqual(self.server.received, [])

    def test_ringo_subscription(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.server = socketserver.TCPServer(("127.0.0.1", 0), RingoHandler)
        self.server.received = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        messages = list(ringo_messages(address=self.server.server_address,
                                       ring_address="AA:BB"))
        self.assertEqual(messages[-1]["type"], "imu")
        self.assertEqual(self.server.received[0]["rings"], ["AA:BB"])


if __name__ == "__main__":
    unittest.main()
