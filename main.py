import sys
import socket

if __name__ == '__main__':
	if len(sys.argv) != 3:
		print("Usage: python main.py <address> <port>")
		exit(1)

	address, port = sys.argv[1], sys.argv[2]
	print(f"testing {address}:{port}")

	ip_version = socket.AF_INET

	info_list = socket.getaddrinfo(address, port, family=ip_version)

	sock = None
	addr = None
	for info in info_list:
		sock = socket.socket(info[0], info[1], info[2])
		try:
			sock.connect(info[4])
			break
		except OSError as err:
			print(f"connect: {err}")

	sock.sendall(b"Hello!\0")
