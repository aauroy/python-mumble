import cffi
import ctypes.util


BITSTREAM_VERSION = 0x80000010


ffi = cffi.FFI()
ffi.cdef("""
typedef ... CELTDecoder;
typedef ... CELTEncoder;

CELTDecoder* celt_decoder_create(int sampling_rate, int channels, int* error);
int celt_decode(CELTDecoder* restrict st, const unsigned char* data, int len,
                int16_t* restrict pcm, int frame_size);
void celt_decoder_destroy(CELTDecoder* restrict st);

CELTEncoder* celt_encoder_create(int sampling_rate, int channels, int* error);
int celt_encode(CELTEncoder* restrict st, const int16_t* pcm, int frame_size,
                unsigned char* compressed, int nbCompressedBytes);
void celt_encoder_destroy(CELTEncoder* restrict st);

const char* celt_strerror(int error);
""")
libcelt = ffi.dlopen(ctypes.util.find_library('celt0.2'))


def celt_check_error(name, error):
    if error > 0:
        raise RuntimeError('{} error {}: {}'.format(
            name, error,
            ffi.string(libcelt.celt_strerror(error)).decode('ascii')))


def celt_call_errout(name, *args):
    error = ffi.new('int*')
    result = getattr(libcelt, name)(*args, error)
    celt_check_error(name, error[0])
    return result


def celt_call_errret(name, *args):
    celt_check_error(name, getattr(libcelt, name)(*args))


FRAME_SIZE = 480


class Decoder(object):
    def __init__(self, rate, channels=1):
        self.rate = rate
        self.channels = channels

        self.decoder = ffi.gc(
            celt_call_errout('celt_decoder_create', self.rate, self.channels),
            libcelt.celt_decoder_destroy)
        self.frame_buffer = ffi.new('int16_t[]', FRAME_SIZE)

    def decode(self, compressed):
        celt_call_errret('celt_decode', self.decoder, compressed,
                         len(compressed), self.frame_buffer, FRAME_SIZE)
        return bytes(ffi.buffer(ffi.cast('char*', self.frame_buffer),
                                FRAME_SIZE * 2))


class Encoder(object):
    def __init__(self, rate, channels=1):
        self.rate = rate
        self.channels = channels

        self.encoder = ffi.gc(
            celt_call_errout('celt_encoder_create', self.rate, self.channels),
            libcelt.celt_encoder_destroy)
        self.frame_buffer = ffi.new('int16_t[]', FRAME_SIZE)

    def encode(self, pcm, size):
        compressed = ffi.new('char[]', size)

        n = libcelt.celt_encode(
            self.encoder, ffi.cast('int16_t*', ffi.new('char[]', pcm)),
            FRAME_SIZE, compressed, size)

        if n < 0:
            celt_check_error('celt_encode', n)

        return bytes(ffi.buffer(compressed, n))


class Codec(object):
    def __init__(self, rate, channels=1):
        self.encoder = Encoder(rate, channels)
        self.decoder = Decoder(rate, channels)
