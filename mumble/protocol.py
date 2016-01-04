import asyncio
import collections
import enum
import logging
import platform
import re
import ssl
import struct
import time

from Crypto.Cipher import AES

from . import entities
from . import Mumble_pb2

CELT_CODECS = {}

try:
    from .codecs import celt011
except:
    pass
else:
    CELT_CODECS[celt011.BITSTREAM_VERSION] = celt011

try:
    from .codecs import celt07
except:
    pass
else:
    CELT_CODECS[celt07.BITSTREAM_VERSION] = celt07


logger = logging.getLogger(__name__)


class UDPTunnelTransport(asyncio.DatagramTransport):
    def __init__(self, control_protocol):
        self.control_protocol = control_protocol

    def sendto(self, data, addr=None):
        assert addr is None
        self.control_protocol.send_payload(
            self.client.PACKET_NUMBERS[Mumble_pb2.UDPTunnel], data)


class ControlProtocol(asyncio.Protocol):
    PACKET_HEADER = struct.Struct('!HI')

    PACKET_TYPES = {
        0: Mumble_pb2.Version,
        1: Mumble_pb2.UDPTunnel,
        2: Mumble_pb2.Authenticate,
        3: Mumble_pb2.Ping,
        4: Mumble_pb2.Reject,
        5: Mumble_pb2.ServerSync,
        6: Mumble_pb2.ChannelRemove,
        7: Mumble_pb2.ChannelState,
        8: Mumble_pb2.UserRemove,
        9: Mumble_pb2.UserState,
        10: Mumble_pb2.BanList,
        11: Mumble_pb2.TextMessage,
        12: Mumble_pb2.PermissionDenied,
        13: Mumble_pb2.ACL,
        14: Mumble_pb2.QueryUsers,
        15: Mumble_pb2.CryptSetup,
        16: Mumble_pb2.ContextActionModify,
        17: Mumble_pb2.ContextAction,
        18: Mumble_pb2.UserList,
        19: Mumble_pb2.VoiceTarget,
        20: Mumble_pb2.PermissionQuery,
        21: Mumble_pb2.CodecVersion,
        22: Mumble_pb2.UserStats,
        23: Mumble_pb2.RequestBlob,
        24: Mumble_pb2.ServerConfig,
        25: Mumble_pb2.SuggestConfig,
    }

    PACKET_NUMBERS = {t: n for n, t in PACKET_TYPES.items()}

    @staticmethod
    def encode_version(major, minor, patch):
        return major << 16 | minor << 8 | patch

    def __init__(self, client, username, password):
        self.client = client
        self.username = username
        self.password = password
        self.buffer = bytearray()
        self._ping_handler = None

    def connection_made(self, transport):
        self.transport = transport
        self.udp_tunnel = UDPTunnelTransport(self)

        self.client.mumble_connection_made()
        self.send_version()
        self.authenticate(self.username, self.password)
        self.start_ping()

    def connection_lost(self, exc):
        if self._ping_handler is not None:
            self._ping_handler.cancel()

    def start_ping(self):
        self.send_message(Mumble_pb2.Ping(timestamp=int(time.time())))
        self._ping_handler = self.client.loop.call_later(20, self.start_ping)

    def send_version(self):
        self.send_message(Mumble_pb2.Version(
            version=self.encode_version(*self.client.MUMBLE_VERSION),
            release='.'.join(str(x) for x in self.client.MUMBLE_VERSION),
            os=platform.system(), os_version=platform.release()))

    def authenticate(self, username, password=None):
        auth_msg = Mumble_pb2.Authenticate(username=self.username)
        if self.password is not None:
            auth_msg.password = self.password
        self.send_message(auth_msg)

    def data_received(self, data):
        self.buffer.extend(data)
        self.process_buffer()

    def process_buffer(self):
        while True:
            try:
                type, length = self.PACKET_HEADER.unpack_from(self.buffer)
            except struct.error:
                # Not enough data.
                break

            end_offset = self.PACKET_HEADER.size + length
            if len(self.buffer) < end_offset:
                # Still not enough data.
                break

            raw_message = bytes(self.buffer[self.PACKET_HEADER.size:end_offset])
            self.buffer[:] = self.buffer[end_offset:]

            assert len(raw_message) == length

            packet_cls = self.PACKET_TYPES[type]

            if packet_cls is Mumble_pb2.UDPTunnel:
                self.mumble_udp_tunnel_received(raw_message)
                continue

            message = packet_cls()
            message.ParseFromString(raw_message)
            self.message_received(message)

    def message_received(self, message):
        logger.debug('[CONTROL] <-- %s\n%s', message.__class__.__name__,
                     message)
        handler_name = 'mumble{}_received'.format(
            re.sub('[A-Z]+', lambda x: '_' + x.group(0).lower(),
                   message.__class__.__name__))

        try:
            handler = getattr(self, handler_name)
        except AttributeError:
            logger.warn('Message %s unhandled.', message.__class__.__name__)
        else:
            handler(message)

    def mumble_version_received(self, message):
        pass

    def mumble_udp_tunnel_received(self, packet):
        self.client.mumble_udp_tunnel_received(packet)

    def mumble_codec_version_received(self, message):
        self.client.mumble_codec_version_received(message.alpha, message.beta,
                                                  message.prefer_alpha,
                                                  message.opus)

    def mumble_crypt_setup_received(self, message):
        self.client.mumble_crypt_setup_received(
            message.key, message.client_nonce, message.server_nonce)

    def mumble_channel_state_received(self, message):
        self.client.mumble_channel_state_received(message)

    def mumble_channel_remove_received(self, message):
        self.client.mumble_channel_remove_received(message.channel_id)

    def mumble_user_state_received(self, message):
        self.client.mumble_user_state_received(message)

    def mumble_user_remove_received(self, message):
        self.client.mumble_user_remove_received(message.session)

    def mumble_server_state_received(self, message):
        self.server_state = message

    def mumble_server_config_received(self, message):
        self.server_config = message
        self.client.connection_ready()

    def mumble_ping_received(self, message):
        pass

    def mumble_text_message_received(self, message):
        self.client.mumble_text_message_received(
            message.actor, message.message, sessions=list(message.session),
            channel_ids=list(message.channel_id))

    def send_payload(self, type, payload):
        self.transport.write(self.PACKET_HEADER.pack(type, len(payload)))
        self.transport.write(payload)

    def send_message(self, message):
        logger.debug('[CONTROL] --> %s\n%s', message.__class__.__name__,
                     message)
        self.send_payload(self.PACKET_NUMBERS[message.__class__],
                          message.SerializeToString())

    def send_text_message(self, actor, message, sessions=None, channel_ids=None,
                          tree_ids=None):
        msg = Mumble_pb2.TextMessage(actor=actor, message=message)

        if sessions is not None:
            msg.session.extend(sessions)

        if channel_ids is not None:
            msg.channel_id.extend(channel_ids)

        if tree_ids is not None:
            msg.tree_id.extend(tree_ids)

        self.send_message(msg)

    def move_user(self, actor, session, channel_id):
        self.send_message(Mumble_pb2.UserState(actor=actor, session=session,
                                               channel_id=channel_id))


class VoiceProtocol(asyncio.DatagramProtocol):
    POSITION_FORMAT = struct.Struct('!fff')
    SAMPLE_RATE = 48000

    class PacketType(enum.IntEnum):
        VOICE_CELT_ALPHA = 0
        PING = 1
        VOICE_SPEEX = 2
        VOICE_CELT_BETA = 3
        VOICE_OPUS = 4

    class Target(enum.IntEnum):
        NORMAL = 0
        SERVER_LOOPBACK = 31

    VoiceTarget = collections.namedtuple('VoiceTarget', ['value'])

    @classmethod
    def _target_to_type(cls, target):
        try:
            return cls.Target(target)
        except ValueError:
            return cls.VoiceTarget(target)

    def __init__(self, client):
        self.client = client
        self.codecs = {}
        self.outgoing_codec = None

    def connection_made(self, transport):
        self.transport = transport

    def setup_crypt(self, key, client_nonce, server_nonce):
        # TODO: figure out what's up with the nonces
        return
        self.client_cipher = AES.new(key, AES.MODE_OCB, nonce=client_nonce)
        self.server_cipher = AES.new(key, AES.MODE_OCB, nonce=server_nonce)

    def setup_codecs(self, alpha, beta, prefer_alpha, opus):
        if alpha:
            self.codecs[self.PacketType.VOICE_CELT_ALPHA] = \
                CELT_CODECS[alpha & 0xffffffff].Codec(self.SAMPLE_RATE)

        if beta:
            self.codecs[self.PacketType.VOICE_CELT_BETA] = \
                CELT_CODECS[beta & 0xffffffff].Codec(self.SAMPLE_RATE)

        if prefer_alpha:
            self.outgoing_codec = self.codecs[self.PacketType.VOICE_CELT_ALPHA]
        else:
            self.outgoing_codec = self.codecs[self.PacketType.VOICE_CELT_BETA]

        if opus:
            raise Exception('opus not supported yet')

    def datagram_received(self, data, addr):
        pass

    def plaintext_data_received(self, data):
        header, payload = data[0], data[1:]

        type = self.PacketType(header >> 5)
        target = self._target_to_type(header & 0b11111)

        if type == self.PacketType.PING:
            ts, _ = self._decode_varint(payload)
            logger.debug('[VOICE] <-- type: %s\ntime: %d', type, payload)
            self.send_voice_data(type, target, payload)
            return

        session, payload = self._decode_varint(payload)
        sequence_number, payload = self._decode_varint(payload)

        # TODO: handle sequence number

        more_frames = True
        while more_frames:
            if type == self.PacketType.VOICE_OPUS:
                audio_header, payload = self._decode_varint(payload)
                length = audio_header & 0b1111111111111
                terminated = audio_header >> 13 == 1
                more_frames = False
                frame, payload = payload[:length], payload[length:]
            else:
                audio_header, payload = payload[0], payload[1:]
                length = audio_header & 0b1111111
                terminated = length == 0
                more_frames = audio_header >> 7 == 1
                frame, payload = payload[:length], payload[length:]

            logger.debug('[VOICE] <-- type: %s\nsession: %d\nlength: %s\n'
                         'terminated: %r\nmore_frames: %r\nframe: %d bytes',
                         type, session, length, terminated, more_frames,
                         len(frame))

            if frame:
                pcm = self.codecs[type].decoder.decode(frame)
                self.client.mumble_voice_heard(session, target, pcm)

    def _decode_varint(self, payload):
        if payload[0] & 0b10000000 == 0:
            return payload[0] & 0b01111111, payload[1:]
        elif payload[0] & 0b01000000 == 0:
            return (payload[0] & 0b00111111 << 8) | payload[1], payload[2:]
        elif payload[0] & 0b00100000 == 0:
            return (payload[0] & 0b00011111 << 16) | (payload[1] << 8) | \
                   payload[2], payload[3:]
        elif payload[0] & 0b00010000 == 0:
            return (payload[0] & 0b00001111 << 24) | (payload[1] << 16) | \
                   (payload[2] << 8) | payload[3], payload[4:]
        elif payload[0] & 0b00001100 == 0:
            return (payload[1] << 16) | (payload[2] << 16) | \
                   (payload[3] << 8) | (payload[4]), payload[5:]
        elif payload[0] & 0b00001100 == 1:
            return (payload[1] << 56) | (payload[2] << 48) | \
                   (payload[3] << 40) | (payload[4] << 32) | \
                   (payload[5] << 24) | (payload[6] << 16) | \
                   (payload[7] << 8) |  payload[8], payload[9:]
        elif payload[0] & 0b00001100 == 2:
            val, payload = self._decode_varint(payload[1:])
            return -val, payload
        elif payload[0] & 0b00001100 == 2:
            return -(payload[0] & 0b00000011), payload[1:]

    def send_voice_data(self, type, target, payload):
        logger.debug('[VOICE] --> type: %s\ntarget: %s\npayload: %d bytes',
                     type, target, len(payload))
        self.transport.sendto(bytes([type.value << 5 | target.value]) + payload)
