import unittest
import subprocess
import communication
import socket
import time
from typing import List
import itertools
import select

SERVER_WAIT_TIME = 1
MESSAGES_WAIT_TIME = 1
HOST = "localhost"

# Path to the server binary
SERVER_PATH = "/home/tom/rep/sik-screen-worms/build/screen-worms-server"

# debug
PRINT_RECEIVED_MESSAGES = False


def start_server(port, args):
	"""
	Run screen worms server in the background
	:param port: server port
	:param args: server other arguments
	:return: server process
	"""
	return subprocess.Popen([SERVER_PATH] + [f"-p {port}"] + args)


def stop_server(server):
	server.kill()
	server.communicate()


def get_events(server_messages: List[communication.ServerMessage]) -> List[communication.Event]:
	return list(itertools.chain.from_iterable(map(lambda x: x.events, server_messages)))


def print_events(server_messages: List[communication.ServerMessage]):
	s = ""
	for i, m in enumerate(server_messages):
		s += f"{m}\n"
	print(s)


class Client:
	def __init__(self, server_host, server_port, session_id, player_name, ip_ver=socket.AF_INET):
		self.server_host = server_host
		self.server_port = server_port
		self.session_id = session_id
		self.player_name = player_name

		self.sock = None
		self.addr = None

		info_list = socket.getaddrinfo(server_host, server_port, family=ip_ver, type=socket.SOCK_DGRAM)
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
		msg = communication.serialize_cts_message(self.session_id, turn_direction, next_expected_event_no,
												  self.player_name)
		self.sock.send(msg)

	def recv_message(self):
		try:
			b_message = self.sock.recv(1024, socket.MSG_DONTWAIT)
		except BlockingIOError:
			return None
		return communication.deserialize_stc_message(b_message)

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
				server_messages.append(communication.deserialize_stc_message(b_message))
		epoll.close()
		return server_messages

	def close(self):
		self.sock.close()


def event_new_game(event_no, width, height, players):
	return communication.Event(-1, event_no, 0, communication.DataNewGame(width, height, players), -1)


def event_pixel(event_no, player_no, x, y):
	return communication.Event(-1, event_no, 1, communication.DataPixel(player_no, x, y), -1)


def event_player_eliminated(event_on, player_no):
	return communication.Event(-1, event_on, 2, communication.DataPlayerEliminated(player_no), -1)


def event_game_over(event_no):
	return communication.Event(-1, event_no, 3, None, -1)


class TestServer200(unittest.TestCase):
	"""
	Does not check event_len and crc32!!!
	"""

	def setUp(self) -> None:
		self.next_session_id = 0
		# for test_xxx, port = 2xxx.
		self.port = 20000 + int(self._testMethodName.split("_")[1])

	def tearDown(self):
		for c in self.clients:
			c.close()
		stop_server(self.server)

	def assertContainsEvents(self, expected: communication.ServerMessage, received: List[communication.ServerMessage]):
		for m in received:
			self.assertEqual(expected.game_id, m.game_id, "Incorrect game id")

		rec_events: List[communication.Event] = get_events(received)

		def cmp(e1: communication.Event, e2: communication.Event):
			return e1.event_no == e2.event_no and e1.event_type == e2.event_type and e1.event_data == e2.event_data

		for e in expected.events:
			self.assertEqual(1, len(list(filter(lambda x: cmp(e, x), rec_events))), f"Event {e} not found")

	def new_client(self, name, ip=socket.AF_INET):
		self.next_session_id += 1
		return Client(HOST, self.port, self.next_session_id, name, ip)

	def new_clients(self, names, ip=socket.AF_INET):
		return list(map(lambda name: self.new_client(name, ip), names))

	def assertClientReceived(self, client: Client, expected: communication.ServerMessage):
		received = client.pull_events()
		if PRINT_RECEIVED_MESSAGES:
			print_events(received)
		self.assertContainsEvents(expected, received)

	def assertClientsReceived(self, clients: List[Client], expected: communication.ServerMessage):
		for client in clients:
			self.assertClientReceived(client, expected)

	def start_server(self, args):
		s = start_server(self.port, args)
		time.sleep(SERVER_WAIT_TIME)  # Wait for server to start.
		return s

	def test_201(self):
		self.server = self.start_server(["-v" "2", "-s 777", "-w 800", "-h 600"])
		self.clients = self.new_clients(["Bob201", "Cezary201"])

		self.clients[0].send_message(1, 0)
		self.clients[1].send_message(2, 0)
		time.sleep(MESSAGES_WAIT_TIME)

		expected_events = communication.ServerMessage(777, [
			event_new_game(0, 800, 600, ["Bob201", "Cezary201"]),
			event_pixel(1, 0, 771, 99),
			event_pixel(2, 1, 18, 331),
			event_pixel(3, 0, 772, 99),
			event_pixel(4, 1, 17, 330),
		])

		self.assertClientsReceived(self.clients, expected_events)

	def test_202(self):
		self.server = self.start_server(["-v 2", "-s 3", "-w 100", "-h 200"])
		self.clients = self.new_clients(["Bob202", "", "Cezary202"])

		self.clients[0].send_message(1, 0)
		self.clients[1].send_message(0, 0)
		self.clients[2].send_message(2, 0)
		time.sleep(MESSAGES_WAIT_TIME)

		expected_events = communication.ServerMessage(3, [
			event_new_game(0, 100, 200, ["Bob202", "Cezary202"]),
			event_pixel(1, 0, 19, 102),
			event_pixel(2, 1, 13, 113),
			event_pixel(3, 0, 20, 102),
			event_pixel(4, 1, 14, 112),
		])

		self.assertClientsReceived(self.clients, expected_events)

	def test_203(self):
		self.server = self.start_server(["-v 2", "-s 2", "-w 800", "-h 600"])
		self.clients = self.new_clients(["Bob203", "", "Cezary203"])

		self.clients[0].send_message(1, 0)
		self.clients[1].sock.send(b"\0")
		self.clients[2].send_message(2, 0)
		time.sleep(MESSAGES_WAIT_TIME)

		expected_events = communication.ServerMessage(2, [
			event_new_game(0, 800, 600, ["Bob203", "Cezary203"]),
			event_pixel(1, 0, 546, 165),
			event_pixel(2, 1, 736, 336),
			event_pixel(3, 0, 547, 165),
			event_pixel(4, 1, 736, 335),
		])

		self.assertClientReceived(self.clients[0], expected_events)
		self.assertClientReceived(self.clients[2], expected_events)

	def test_204(self):
		self.server = self.start_server(["-v" "2", "-s 777", "-w 800", "-h 600"])
		self.clients = self.new_clients(["Bob201", "Cezary201"], socket.AF_INET6)

		self.clients[0].send_message(1, 0)
		self.clients[1].send_message(2, 0)
		time.sleep(MESSAGES_WAIT_TIME)

		expected_events = communication.ServerMessage(777, [
			event_new_game(0, 800, 600, ["Bob201", "Cezary201"]),
			event_pixel(1, 0, 771, 99),
			event_pixel(2, 1, 18, 331),
			event_pixel(3, 0, 772, 99),
			event_pixel(4, 1, 17, 330),
		])

		self.assertClientsReceived(self.clients, expected_events)


if __name__ == '__main__':
	unittest.main()
