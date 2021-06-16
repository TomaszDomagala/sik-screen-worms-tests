import socket
import argparse
import select
import string
import time
from linuxfd import timerfd
import communication
import random


def random_name(n=20):
	return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))


def init_parser():
	default_session_id = int(time.time() * 1000)
	default_name = random_name(5)

	parser = argparse.ArgumentParser()
	parser.add_argument("-a", "--addr", default="localhost")
	parser.add_argument("-p", "--port", default="2021")
	parser.add_argument("-s", "--session", default=default_session_id, type=int)
	parser.add_argument("-n", "--name", default=default_name)

	return parser


if __name__ == '__main__':
	args = init_parser().parse_args()

	info_list = socket.getaddrinfo(args.addr, args.port, family=socket.AF_INET, type=socket.SOCK_DGRAM)

	sock = None
	addr = None
	for info in info_list:
		try:
			sock = socket.socket(info[0], info[1], info[2])
			addr = info[4]
			sock.connect(addr)
			break
		except OSError as err:
			print(f"connect: {err}")

	print(f"testing server {addr[0]}:{addr[1]}")

	epoll = select.epoll()
	epoll.register(sock.fileno(), eventmask=select.EPOLLIN)

	timer = timerfd()

	interval_ms = 30  # default 30
	interval_s = float(interval_ms) / 1000.0

	timer.settime(interval_s, interval_s)
	epoll.register(timer.fileno(), eventmask=select.EPOLLIN)

	next_event_no = 0
	game_id = 0
	while True:
		epoll_events = epoll.poll(timeout=-1, maxevents=10)

		for (fd, event_mask) in epoll_events:
			if fd == timer.fileno():
				timer.read()
				m_client = communication.serialize_cts_message(args.session, 1, next_event_no, args.name)
				if sock.send(m_client) != len(m_client):
					print("partial send")
				print(f"neen={next_event_no} sent {len(m_client)} bytes to server")

			elif fd == sock.fileno():
				b_message = sock.recv(1024)
				print(f"neen={next_event_no} received {len(b_message)} bytes from server")
				try:
					mess = communication.deserialize_stc_message(b_message)
				except Exception as err:
					print(len(b_message))
					print(b_message)
					print(err)
					exit(1)

				if game_id != mess.game_id:
					game_id = mess.game_id
					next_event_no = 0
				for e in mess.events:
					if e.event_no == next_event_no:
						next_event_no += 1
					if e.event_type == 3:
						print("GAME OVER")
						next_event_no = 0
