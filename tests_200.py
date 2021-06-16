import unittest
import subprocess
import communication
import socket
import time
from typing import List
import itertools
import select
import configparser

config = configparser.ConfigParser()


def start_server(port, args):
	"""
	Run screen worms server in the background
	:param port: server port
	:param args: server other arguments
	:return: server process
	"""
	out = None if config.getboolean("TESTS_200_DEBUG", "PRINT_SERVER_STDOUT") else subprocess.DEVNULL
	err = None if config.getboolean("TESTS_200_DEBUG", "PRINT_SERVER_STDERR") else subprocess.DEVNULL
	return subprocess.Popen([config.get("TESTS_200", "SERVER_PATH")] + [f"-p {port}"] + args, stdout=out, stderr=err)


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

	def send_message(self, turn_direction, next_expected_event_no=0):
		msg = communication.serialize_cts_message(self.session_id, turn_direction, next_expected_event_no,
												  self.player_name)
		self.sock.send(msg)
		time.sleep(config.getfloat("TESTS_200", "AFTER_MSG_WAIT"))

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
			events = epoll.poll(timeout=config.getfloat("TESTS_200", "EPOLL_TIMEOUT"), maxevents=-1)
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


def events_equal(e1: communication.Event, e2: communication.Event):
	return e1.event_no == e2.event_no and e1.event_type == e2.event_type and e1.event_data == e2.event_data


class TestServer200(unittest.TestCase):
	"""
	Does not check event_len and crc32!!!
	"""

	def setUp(self) -> None:
		self.next_session_id = 0
		# for test_xxx, server port = 20xxx.
		self.port = 20000 + int(self._testMethodName.split("_")[1])

	def tearDown(self):
		for c in self.clients:
			c.close()
		stop_server(self.server)

	def assertContainsEvents(self, expected: communication.ServerMessage, received: List[communication.ServerMessage]):
		if config.getboolean("TESTS_200_DEBUG", "PRINT_RECEIVED_MESSAGES"):
			print_events(received)

		for m in received:
			self.assertEqual(expected.game_id, m.game_id, "Incorrect game id")

		rec_events: List[communication.Event] = get_events(received)
		for e in expected.events:
			num = len(list(filter(lambda x: events_equal(e, x), rec_events)))
			self.assertLessEqual(1, num, f"Event {e} not found")

	def new_client(self, name, ip=socket.AF_INET):
		self.next_session_id += 1
		return Client(config.get("TESTS_200", "HOST"), self.port, self.next_session_id, name, ip)

	def new_clients(self, names, ip=socket.AF_INET):
		return list(map(lambda name: self.new_client(name, ip), names))

	def assertClientReceived(self, client: Client, expected: communication.ServerMessage):
		received = client.pull_events()
		self.assertContainsEvents(expected, received)

	def assertClientsReceived(self, clients: List[Client], expected: communication.ServerMessage):
		for client in clients:
			self.assertClientReceived(client, expected)

	def start_server(self, seed, width=800, height=600, rounds_per_sec=2):
		args = [f"-s {seed}", f"-v {rounds_per_sec}", f"-w {width}", f"-h {height}"]
		s = start_server(self.port, args)
		time.sleep(config.getfloat("TESTS_200", "SERVER_INIT_TIME"))  # Wait for server to start.
		return s

	def wait_server(self):
		time.sleep(config.getfloat("TESTS_200", "SERVER_RUN_TIME"))

	def test_201(self):
		"""
		Parametry serwera: -v 2 -s 777 -w 800 -h 600
		Klient 0: turn_direction = 1, next_expected_event_no = 0, player_name = Bob201
		Klient 1: turn_direction = 2, next_expected_event_no = 0, player_name = Cezary201
		"""
		self.server = self.start_server(777)
		self.clients = self.new_clients(["Bob201", "Cezary201"])

		self.clients[0].send_message(1, 0)
		self.clients[1].send_message(2, 0)
		self.wait_server()

		expected_events = communication.ServerMessage(777, [
			event_new_game(0, 800, 600, ["Bob201", "Cezary201"]),
			event_pixel(1, 0, 771, 99),
			event_pixel(2, 1, 18, 331),
			event_pixel(3, 0, 772, 99),
			event_pixel(4, 1, 17, 330),
		])

		self.assertClientsReceived(self.clients, expected_events)

	def test_202(self):
		"""
		Parametry serwera: -v 2 -s 3 -h 200 -w 100
		Klient 0: turn_direction = 1, next_expected_event_no = 0, player_name = Bob202
		Klient 1: turn_direction = 0, next_expected_event_no = 0, bez nazwy gracza
		Klient 2: turn_direction = 2, next_expected_event_no = 0, player_name = Cezary202
		"""
		self.server = self.start_server(3, 100, 200)
		self.clients = self.new_clients(["Bob202", "", "Cezary202"])

		self.clients[0].send_message(1, 0)
		self.clients[1].send_message(0, 0)
		self.clients[2].send_message(2, 0)
		self.wait_server()

		expected_events = communication.ServerMessage(3, [
			event_new_game(0, 100, 200, ["Bob202", "Cezary202"]),
			event_pixel(1, 0, 19, 102),
			event_pixel(2, 1, 13, 113),
			event_pixel(3, 0, 20, 102),
			event_pixel(4, 1, 14, 112),
		])

		self.assertClientsReceived(self.clients, expected_events)

	def test_203(self):
		"""
		Parametry serwera: -v 2 -s 2 -w 800 -h 600
		Klient 0: turn_direction = 1, next_expected_event_no = 0, player_name = Bob203
		Klient 1: za krótki komunikat – jeden bajt o wartości 0
		Klient 2: turn_direction = 2, next_expected_event_no = 0, player_name = Cezary203
		"""
		self.server = self.start_server(2)
		self.clients = self.new_clients(["Bob203", "", "Cezary203"])

		self.clients[0].send_message(1, 0)
		self.clients[1].sock.send(b"\0")
		self.clients[2].send_message(2, 0)
		self.wait_server()

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
		"""
		Parametry serwera: -v 2 -s 777 -w 800 -h 600
		Klient 0: turn_direction = 1, next_expected_event_no = 0, player_name = Bob205, używa IPv6
		Klient 1: turn_direction = 2, next_expected_event_no = 0, player_name = Cezary205, używa IPv6
		"""
		self.server = self.start_server(777)
		self.clients = self.new_clients(["Bob201", "Cezary201"], socket.AF_INET6)

		self.clients[0].send_message(1, 0)
		self.clients[1].send_message(2, 0)
		self.wait_server()

		expected_events = communication.ServerMessage(777, [
			event_new_game(0, 800, 600, ["Bob201", "Cezary201"]),
			event_pixel(1, 0, 771, 99),
			event_pixel(2, 1, 18, 331),
			event_pixel(3, 0, 772, 99),
			event_pixel(4, 1, 17, 330),
		])

		self.assertClientsReceived(self.clients, expected_events)

	def test_205(self):
		"""
		Parametry serwera: -v 2 -s 65535 -h 2048 -w 2048
		Klient 0: turn_direction = 1, next_expected_event_no = 0, player_name = Bob206, używa IPv6
		Klient 1: turn_direction = 2, next_expected_event_no = 0, player_name = Ala206, używa IPv6
		Sprawdza sortowanie nazw graczy.
		"""
		self.server = self.start_server(65535, 2048, 2048)
		self.clients = self.new_clients(["Bob206", "Ala206"], socket.AF_INET6)

		self.clients[0].send_message(1, 0)
		self.clients[1].send_message(2, 0)
		self.wait_server()

		expected_events = communication.ServerMessage(65535, [
			event_new_game(0, 2048, 2048, ["Ala206", "Bob206"]),
			event_pixel(1, 0, 1250, 789),
			event_pixel(2, 1, 1415, 1456),
			event_pixel(3, 0, 1250, 790),
			event_pixel(4, 1, 1415, 1457),
		])

		self.assertClientsReceived(self.clients, expected_events)

	def test_206(self):
		"""
		Parametry serwera: -v 2 -s 7 -w 800 -h 600
		Klient 0: turn_direction = 3, next_expected_event_no = 0, player_name = Cezary207
		Klient 1: turn_direction = 1, next_expected_event_no = 0, player_name = Ala207
		Klient 2: turn_direction = 2, next_expected_event_no = 0, player_name = Bob207
		Klient 0 wysyła błędną wartość turn_direction.
		"""
		self.server = self.start_server(7)
		self.clients = self.new_clients(["Cezary207", "Ala207", "Bob207"])

		self.clients[0].send_message(3, 0)
		self.clients[1].send_message(1, 0)
		self.clients[2].send_message(2, 0)
		self.wait_server()

		expected_events = communication.ServerMessage(7, [
			event_new_game(0, 800, 600, ["Ala207", "Bob207"]),
			event_pixel(1, 0, 711, 141),
			event_pixel(2, 1, 394, 3),
			event_pixel(3, 0, 712, 142),
			event_pixel(4, 1, 393, 3),
		])

		self.assertClientsReceived(self.clients[1:], expected_events)
		self.assertEqual(self.clients[0].pull_events(), [])

	def test_207(self):
		"""
		Parametry serwera: -v 2 -s 8 -w 800 -h 600
		Klient 0: turn_direction = 1, next_expected_event_no = 0, błędna nazwa gracza – pojedyncza spacja
		Klient 1: turn_direction = 1, next_expected_event_no = 0, player_name = Ala208
		Klient 2: turn_direction = 2, next_expected_event_no = 0, player_name = Bob208
		"""
		self.server = self.start_server(8)
		self.clients = self.new_clients([" ", "Ala208", "Bob208"])

		self.clients[0].send_message(1, 0)
		self.clients[1].send_message(1, 0)
		self.clients[2].send_message(2, 0)
		self.wait_server()

		expected_events = communication.ServerMessage(8, [
			event_new_game(0, 800, 600, ["Ala208", "Bob208"]),
			event_pixel(1, 0, 584, 278),
			event_pixel(2, 1, 271, 471),
			event_pixel(3, 0, 584, 279),
			event_pixel(4, 1, 271, 470),
		])

		self.assertClientsReceived(self.clients[1:], expected_events)
		self.assertEqual(self.clients[0].pull_events(), [])

	def test_208(self):
		"""
		Parametry serwera: -v 2 -s 9 -w 800 -h 600
		Klient 0: turn_direction = 2, next_expected_event_no = 0, błędna nazwa gracza – znak o kodzie 0
		Klient 1: turn_direction = 1, next_expected_event_no = 0, player_name = Ala209
		Klient 2: turn_direction = 2, next_expected_event_no = 0, player_name = Bob209
		"""
		self.server = self.start_server(9)
		self.clients = self.new_clients(["\0", "Ala209", "Bob209"])

		self.clients[0].send_message(2)
		self.clients[1].send_message(1)
		self.clients[2].send_message(2)
		self.wait_server()

		expected_events = communication.ServerMessage(9, [
			event_new_game(0, 800, 600, ["Ala209", "Bob209"]),
			event_pixel(1, 0, 457, 415),
			event_pixel(2, 1, 239, 448),
			event_pixel(3, 0, 458, 416),
			event_pixel(4, 1, 239, 449),
		])

		self.assertClientsReceived(self.clients[1:], expected_events)
		self.assertEqual(self.clients[0].pull_events(), [])

	def test_209(self):
		"""
		Parametry serwera: -v 2 -s 10 -w 800 -h 600
		Klient 0: turn_direction = 2, next_expected_event_no = 0, player_name = abcdefghijklmnopqrstu
		Klient 1: turn_direction = 1, next_expected_event_no = 0, player_name = ala210
		Klient 2: turn_direction = 2, next_expected_event_no = 0, player_name = bob210
		Błędna nazwa gracza – klient 0 wysyła za długą nazwę gracza (21 znaków).
		"""
		self.server = self.start_server(10)
		self.clients = self.new_clients(["abcdefghijklmnopqrstu", "ala210", "bob210"])

		self.clients[0].send_message(2)
		self.clients[1].send_message(1)
		self.clients[2].send_message(2)
		self.wait_server()

		expected_events = communication.ServerMessage(10, [
			event_new_game(0, 800, 600, ["ala210", "bob210"]),
			event_pixel(1, 0, 330, 552),
			event_pixel(2, 1, 207, 316),
			event_pixel(3, 0, 329, 553),
			event_pixel(4, 1, 206, 316),
		])

		self.assertClientsReceived(self.clients[1:], expected_events)
		self.assertEqual(self.clients[0].pull_events(), [])

	def test_210(self):
		"""
		Parametry serwera: -v 2 -s 11 -w 800 -h 600
		Klient 0: turn_direction = 0, next_expected_event_no = 0, player_name = Ala211, używa IPv4
		Klient 1: turn_direction = 1, next_expected_event_no = 0, player_name = Bob211, używa IPv6
		Klient 0: turn_direction = 1, next_expected_event_no = 0, player_name = Ala211, używa IPv4
		"""
		self.server = self.start_server(11)
		self.clients = [self.new_client("Ala211", socket.AF_INET), self.new_client("Bob211", socket.AF_INET6)]

		self.clients[0].send_message(0)
		self.clients[1].send_message(1)
		self.clients[0].send_message(1)
		self.wait_server()

		expected_events = communication.ServerMessage(11, [
			event_new_game(0, 800, 600, ["Ala211", "Bob211"]),
			event_pixel(1, 0, 203, 580),
			event_pixel(2, 1, 84, 293),
			event_pixel(3, 0, 203, 581),
			event_pixel(4, 1, 85, 293),
		])
		self.assertClientsReceived(self.clients, expected_events)

	def test_211(self):
		"""
		Parametry serwera: -v 2 -s 12 -w 800 -h 600
		Klient 0: turn_direction = 1, next_expected_event_no = 0, player_name = Ala212
		Klient 1: turn_direction = 1, next_expected_event_no = 0, player_name = Bob212
		Klient 0: turn_direction = 1, next_expected_event_no = 1, player_name = Ala212
		"""
		self.server = self.start_server(12)
		self.clients = self.new_clients(["Ala212", "Bob212"])

		self.clients[0].send_message(1, 0)
		self.clients[1].send_message(1, 0)
		time.sleep(1)
		self.clients[0].send_message(1, 1)
		time.sleep(1)

		events = [
			event_new_game(0, 800, 600, ["Ala212", "Bob212"]),
			event_pixel(1, 0, 76, 117),
			event_pixel(2, 1, 52, 161),
			event_pixel(3, 0, 75, 118),
			event_pixel(4, 1, 52, 162),
			event_pixel(5, 0, 74, 118),
			event_pixel(6, 1, 53, 163),
		]
		expected_events = communication.ServerMessage(12, events)

		c0_messages = self.clients[0].pull_events()
		c1_messages = self.clients[1].pull_events()

		# Check for all messages.
		self.assertContainsEvents(expected_events, c0_messages)
		self.assertContainsEvents(expected_events, c1_messages)

		# Check for duplicates in client0.
		c0_events = get_events(c0_messages)

		for dup_event in events[1:5]:
			num = len(list(filter(lambda x: events_equal(dup_event, x), c0_events)))
			self.assertEqual(2, num, f"Event ({dup_event}) is not duplicated")

	def test_212(self):
		"""
		Parametry serwera: -v 2 -s 13 -w 800 -h 600
		Klient 0: turn_direction = 1, next_expected_event_no = 0, player_name = Alicja213
		Klient 1: turn_direction = 1, next_expected_event_no = 0, player_name = Bolek213
		Klient 2: turn_direction = 1, next_expected_event_no = 0, player_name = Cezary213
		Gracz Cezary213 nie załapuje się na rozgrywkę.
		"""
		# I don't know how the official tests are implemented, but
		# this test probably does not makes sense with zero AFTER_MSG_WAIT
		# because messages not always would be sent in the same order.

		self.server = self.start_server(13)
		self.clients = self.new_clients(["Alicja213", "Bolek213", "Cezary213"])

		self.clients[0].send_message(1)
		self.clients[1].send_message(1)
		self.clients[2].send_message(1)
		self.wait_server()

		expected_events = communication.ServerMessage(13, [
			event_new_game(0, 800, 600, ["Alicja213", "Bolek213"]),
			event_pixel(1, 0, 749, 254),
			event_pixel(2, 1, 20, 29),
			event_pixel(3, 0, 749, 255),
			event_pixel(4, 1, 20, 28),
		])

		self.assertClientsReceived(self.clients, expected_events)

	def test_213(self):
		"""
		Parametry serwera: -v 2 -s 14 -w 800 -h 600
		Klient 0: turn_direction = 1, next_expected_event_no = 0, player_name = ala214
		Klient 1: turn_direction = 2, next_expected_event_no = 0, player_name = abcdefghijklmnopqrst
		Klient 1 wysyła nazwę gracza o maksymalnej długości (20 znaków).
		"""
		self.server = self.start_server(14)
		self.clients = self.new_clients(["ala214", "abcdefghijklmnopqrst"])

		self.clients[0].send_message(1)
		self.clients[1].send_message(2)
		self.wait_server()

		expected_events = communication.ServerMessage(14, [
			event_new_game(0, 800, 600, ["abcdefghijklmnopqrst", "ala214"]),
			event_pixel(1, 0, 622, 391),
			event_pixel(2, 1, 697, 6),
			event_pixel(3, 0, 621, 391),
			event_pixel(4, 1, 697, 7),
		])

		self.assertClientsReceived(self.clients, expected_events)

	def test_214(self):
		"""
		Parametry serwera: -v 2 -s 15 -w 800 -h 600
		Klient 0: turn_direction = 1, next_expected_event_no = 0, player_name = Ala215
		Tu jest przerwa 3 sekundy. Ala215 zostaje odłączona.
		Klient 1: turn_direction = 1, next_expected_event_no = 0, player_name = Bobek215
		Klient 2: turn_direction = 1, next_expected_event_no = 0, player_name = Cezary215
		"""
		self.server = self.start_server(15)
		self.clients = self.new_clients(["Ala215", "Bobek215", "Cezary215"])

		self.clients[0].send_message(1)
		time.sleep(3)
		self.clients[1].send_message(1)
		self.clients[2].send_message(1)
		self.wait_server()

		expected_events = communication.ServerMessage(15, [
			event_new_game(0, 800, 600, ["Bobek215", "Cezary215"]),
			event_pixel(1, 0, 495, 528),
			event_pixel(2, 1, 665, 474),
			event_pixel(3, 0, 494, 529),
			event_pixel(4, 1, 664, 475),
		])

		self.assertClientsReceived(self.clients[1:], expected_events)
		self.assertEqual(self.clients[0].pull_events(), [], "Disconnected client0 received events.")


if __name__ == '__main__':
	config.read("test_config.ini")
	unittest.main()
