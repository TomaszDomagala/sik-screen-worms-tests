import struct
from dataclasses import dataclass, field
from typing import List, Union


def serialize_cts_message(session_id, turn_direction, next_expected_event_no, player_name):
	"""
	Return client to server message as bytes array.
	"""
	name_bytes = str.encode(player_name)
	name_len = len(name_bytes)
	return struct.pack(f"!QBI{name_len}s", session_id, turn_direction, next_expected_event_no, name_bytes)


@dataclass
class DataNewGame:
	max_x: int
	max_y: int
	players_names: List[str]

	def __str__(self):
		return f"NEW_GAME {self.max_x} {self.max_y} {(' '.join(self.players_names))}"


@dataclass
class DataPixel:
	player_num: int
	x: int
	y: int

	def __str__(self):
		return f"PIXEL {self.player_num} {self.x} {self.y}"


@dataclass
class DataPlayerEliminated:
	player_num: int


@dataclass
class Event:
	event_len: int
	event_no: int
	event_type: int
	event_data: Union[DataNewGame, DataPixel, DataPlayerEliminated]
	crc32: int

	def __str__(self):
		return f"ev {self.event_no} {self.event_data}"


@dataclass
class ServerMessage:
	game_id: int
	events: List[Event] = field(default_factory=list)

	def __str__(self):
		events_str = list(map(lambda x: f"game {self.game_id} {x}", self.events))
		return "\n".join(events_str)


def deserialize_stc_message_new_game(b_data) -> DataNewGame:
	max_x, max_y = struct.unpack("!II", b_data[:8])
	b_data = b_data[8:]
	names = []
	b_names = bytes.split(b_data, b"\0")
	for b_name in b_names:
		names.append(bytes.decode(b_name, "utf-8"))

	return DataNewGame(max_x, max_y, names[:-1])


def deserialize_stc_message_pixel(b_data) -> DataPixel:
	player_num, x, y = struct.unpack("!BII", b_data)
	return DataPixel(player_num, x, y)


def deserialize_stc_message_player_eliminated(b_data) -> DataPlayerEliminated:
	player_num, = struct.unpack("!B", b_data)
	return DataPlayerEliminated(player_num)


def deserialize_stc_message(b_message) -> ServerMessage:
	game_id, = struct.unpack("!I", b_message[:4])
	server_message = ServerMessage(game_id)

	b_message = b_message[4:]

	while len(b_message):
		b_header = b_message[:9]
		event_len, event_no, event_type = struct.unpack("!IIB", b_header)
		b_data = b_message[9:event_len + 4]
		b_crc32 = b_message[event_len + 4:event_len + 8]

		crc32, = struct.unpack("!I", b_crc32)
		# TODO check crc32 match

		event_data = None
		if event_type == 0:
			event_data = deserialize_stc_message_new_game(b_data)
		elif event_type == 1:
			event_data = deserialize_stc_message_pixel(b_data)
		elif event_type == 2:
			event_data = deserialize_stc_message_player_eliminated(b_data)
		elif event_type == 3:
			event_data = None
		else:
			raise Exception(f"invalid event_type={event_type}")

		ev = Event(event_len, event_no, event_type, event_data, crc32)
		server_message.events.append(ev)

		b_message = b_message[event_len + 8:]

	return server_message
