import socket
import unittest
from ucon_trailcam_smtp.h4_traffic import TrafficStats, SocketModuleProxy


class TrafficTests(unittest.TestCase):
    def test_udp_loopback(self):
        stats = TrafficStats(lambda: 'test')
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
            peer.bind(('127.0.0.1', 0))
            peer.settimeout(2)
            with SocketModuleProxy(stats).socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.bind(('127.0.0.1', 0))
                client.settimeout(2)
                client.sendto(b'abc', peer.getsockname())
                data, addr = peer.recvfrom(100)
                self.assertEqual(data, b'abc')
                peer.sendto(b'hello', addr)
                self.assertEqual(client.recvfrom(100)[0], b'hello')
        self.assertEqual(stats.bytes[('test', 'tx')], 3)
        self.assertEqual(stats.bytes[('test', 'rx')], 5)
        self.assertEqual(sum(stats.packets.values()), 2)
