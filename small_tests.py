import unittest
import subprocess
import messages
import socket
import time
from typing import List
import itertools
import select


def start_server(args):
	"""
	Run screen worms server in the background
	:param args: server arguments
	:return: server process
	"""
	return subprocess.Popen(["./screen-worms-server"] + args)


def get_events(server_messages: List[messages.ServerMessage]):


class Client:
	def __init__(self, server_host, server_port, session_id, player_name):
		self.server_host = server_host
		self.server_port = server_port
		self.session_id = session_id
		self.player_name = player_name

		self.sock = None
		self.addr = None

		info_list = socket.getaddrinfo(server_host, server_port, family=socket.AF_INET, type=socket.SOCK_DGRAM)
		connected = False
		for info in info_list:
			try:
				self.sock = socket.socket(info[0], info[1], info[2])
				self.addr = info[4]
				self.sock.connect(self.addr)
				connected = True
				break
			except OSError as err:
				print(f"connect: {err}")
				pass

		if not connected:
			raise ConnectionError("Cannot connect to the server")

	def send_message(self, turn_direction, next_expected_event_no):
		if turn_direction == -1:
			turn_direction = 2
		msg = messages.serialize_cts_message(self.session_id, turn_direction, next_expected_event_no, self.player_name)
		self.sock.send(msg)

	def recv_message(self):
		try:
			b_message = self.sock.recv(1024, socket.MSG_DONTWAIT)
		except BlockingIOError:
			return None
		return messages.deserialize_stc_message(b_message)

	def pull_events(self):
		epoll = select.epoll()
		epoll.register(self.sock.fileno(), eventmask=select.EPOLLIN)

		server_messages = []
		while True:
			events = epoll.poll(timeout=2, maxevents=-1)
			if len(events) == 0:
				break
			for (fd, mask) in events:
				b_message = self.sock.recv(1024)
				server_messages.append(messages.deserialize_stc_message(b_message))
		return server_messages

	# server_messages = []
	# while True:
	# 	msg = self.recv_message()
	# 	if msg is None:
	# 		break
	# 	server_messages.append(msg)
	# return []

	def close(self):
		self.sock.close()


host = "localhost"
port = 2021


def event_new_game(event_no, width, height, players):
	return messages.Event(-1, event_no, 0, messages.DataNewGame(width, height, players), -1)


def event_pixel(event_no, player_no, x, y):
	return messages.Event(-1, event_no, 1, messages.DataPixel(player_no, x, y), -1)


class TestServer200(unittest.TestCase):
	"""
	Does not check event_len and crc32!!!
	"""

	def assertContainsEvents(self, expected: messages.ServerMessage, received: List[messages.ServerMessage]):
		for m in received:
			self.assertEqual(expected.game_id, m.game_id, "Incorrect game id")

		rec_events: List[messages.Event] = list(itertools.chain.from_iterable(map(lambda x: x.events, received)))

		# for e in rec_events:
		# 	print(e)

		def cmp(e1: messages.Event, e2: messages.Event):
			return e1.event_no == e2.event_no and e1.event_type == e2.event_type and e1.event_data == e2.event_data

		for e in expected.events:
			self.assertEqual(1, len(list(filter(lambda x: cmp(e, x), rec_events))), f"Event {e} not found")

	def test_201(self):
		# server = start_server(["-v 2", "-s 777"])
		client0 = Client(host, port, 1, "Bob201")
		client1 = Client(host, port, 2, "Cezary201")

		client0.send_message(1, 0)
		client1.send_message(1, 0)
		time.sleep(2)

		c0_events = client0.pull_events()
		c1_events = client1.pull_events()
		# print(c0_events)

		client0.close()
		client1.close()

		expected_events = messages.ServerMessage(777, [
			event_new_game(0, 800, 600, ["Bob201", "Cezary201"]),
			event_pixel(1, 0, 771, 99),
			event_pixel(2, 1, 18, 331),
			event_pixel(3, 0, 772, 99),
			event_pixel(4, 1, 17, 330),
		])

		self.assertContainsEvents(expected_events, c0_events)
		self.assertContainsEvents(expected_events, c1_events)

	def test_202(self):
		# server = start_server(["-v 2", "-s 3", "-w 100 -h 200"])

		client0 = Client(host, port, 1, "Bob202")
		client1 = Client(host, port, 2, "")
		client2 = Client(host, port, 3, "Cezary202")

		client0.send_message(1, 0)
		client1.send_message(0, 0)
		client2.send_message(-1, 0)
		time.sleep(2)

		c0_events = client0.pull_events()
		c1_events = client1.pull_events()
		c2_events = client2.pull_events()

		client0.close()
		client1.close()
		client2.close()

		expected_events = messages.ServerMessage(3, [
			event_new_game(0, 100, 200, ["Bob202", "Cezary202"]),
			event_pixel(1, 0, 19, 102),
			event_pixel(2, 1, 13, 113),
			event_pixel(3, 0, 20, 102),
			event_pixel(4, 1, 14, 112)
		])

		self.assertContainsEvents(expected_events, c0_events)
		self.assertContainsEvents(expected_events, c1_events)
		self.assertContainsEvents(expected_events, c2_events)

	def test_203(self):
		# server = start_server(["-v 2", "-s 2", "-w 800 -h 600")

		client0 = Client(host, port, 1, "Bob203")
		client1 = Client(host, port, 2, "")
		client2 = Client(host, port, 3, "Cezary203")

		client0.send_message(1, 0)
		client1.sock.send(b"\0")
		client2.send_message(-1, 0)
		time.sleep(2)

		c0_events = client0.pull_events()
		c2_events = client2.pull_events()

		for client in [client0, client1, client2]:
			client.close()

		expected_events = messages.ServerMessage(2, [
			event_new_game(0, 800, 600, ["Bob203", "Cezary203"]),
			event_pixel(1, 0, 546, 165),
			event_pixel(2, 1, 736, 336),
			event_pixel(3, 0, 547, 165),
			event_pixel(4, 1, 736, 335),
		])

		self.assertContainsEvents(expected_events, c0_events)
		self.assertContainsEvents(expected_events, c2_events)

	def test_204(self):

# server.kill()
