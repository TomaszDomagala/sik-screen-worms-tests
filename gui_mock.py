import socket
import argparse
import select
from linuxfd import timerfd


def init_parser():
	parser = argparse.ArgumentParser()
	parser.add_argument("-p", "--port", default="20210")

	return parser


if __name__ == '__main__':
	args = init_parser().parse_args()

	info_list = socket.getaddrinfo(None, args.port, family=socket.AF_INET, type=socket.SOCK_STREAM)
	sock = None
	addr = None

	for info in info_list:
		try:
			sock = socket.socket(info[0], info[1], info[2])
			addr = info[4]
			sock.bind(addr)
			break
		except OSError as err:
			print(f"socket init: {err}")
			sock = None

	if sock is None:
		print("cannot start server")
		exit(1)

	print(f"listening at port {addr[1]}")
	sock.listen(0)

	epoll = select.epoll()
	epoll.register(sock.fileno(), eventmask=select.EPOLLIN)

	timer = timerfd()
	timer.settime(1, 1)
	epoll.register(timer.fileno(), eventmask=select.EPOLLIN)

	clients = {}

	while True:
		epoll_events = epoll.poll(timeout=-1, maxevents=10)

		for (fd, event_mask) in epoll_events:
			if fd == sock.fileno():
				# new client
				client_sock, client_addr = sock.accept()
				print(f"new client {client_addr[0]}:{client_addr[1]}")
				epoll.register(client_sock.fileno(), eventmask=select.EPOLLIN)
				clients[client_sock.fileno()] = client_sock
			elif fd == timer.fileno():
				ticks = timer.read()
				for client in clients.values():
					client.sendall(b"LEFT_KEY_DOWN\n")

			elif fd in clients:
				if event_mask & select.EPOLLHUP:
					client_sock = clients[fd]
					client_sock.close()
					epoll.unregister(fd)
					del clients[fd]
					print("connection closed")
					continue
				if event_mask & select.EPOLLIN:
					client_sock = clients[fd]
					data = client_sock.recv(1024)
					if len(data):
						print(f"client data: {data}")
