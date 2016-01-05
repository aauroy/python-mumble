import cffi
import ctypes.util


BITSTREAM_VERSION = 0x8000000b


ffi = cffi.FFI()
ffi.cdef("""
typedef ... CELTMode;
typedef ... CELTEncoder;
typedef ... CELTDecoder;

CELTMode* celt_mode_create(int32_t Fs, int frame_size, int* error);
void celt_mode_destroy(CELTMode* mode);

CELTDecoder* celt_decoder_create(CELTMode* mode, int channels, int* error);
int celt_decode(CELTDecoder* st, const unsigned char* data, int len,
                int16_t* pcm);
void celt_decoder_destroy(CELTDecoder* st);

CELTEncoder* celt_encoder_create(CELTMode* mode, int channels, int* error);
int celt_encode(CELTEncoder* st, const int16_t* pcm,
                int16_t* optional_synthesis, unsigned char* compressed,
                int nbCompressedBytes);
void celt_encoder_destroy(CELTEncoder* st);

const char* celt_strerror(int error);
""")


def _load_libcelt():
    for library_name in ['libcelt0.so.0', 'libcelt0.0.dylib',
                         'celt.0.7.0.dll']:
        try:
            return ffi.dlopen(library_name)
        except OSError:
            pass
    else:
        raise ImportError('could not load libcelt')


libcelt = _load_libcelt()


def celt_check_error(name, error):
    if error != 0:
        raise RuntimeError('{} error: {}'.format(
            name,
            ffi.string(libcelt.celt_strerror(error)).decode('ascii')))


def celt_call_errout(name, *args):
    error = ffi.new('int*')
    result = getattr(libcelt, name)(*args, error)
    celt_check_error(name, error[0])
    return result


def celt_call_errret(name, *args):
    celt_check_error(name, getattr(libcelt, name)(*args))


def create_mode(rate, frame_size):
    return ffi.gc(
        celt_call_errout('celt_mode_create', rate, frame_size),
        libcelt.celt_mode_destroy)


class Decoder(object):
    def __init__(self, rate, frame_size=None, channels=1):
        if frame_size is None:
            frame_size = rate // 100

        self.rate = rate
        self.frame_size = frame_size
        self.channels = channels

        self.mode = create_mode(self.rate, self.frame_size)
        self.decoder = ffi.gc(
            celt_call_errout('celt_decoder_create', self.mode, self.channels),
            libcelt.celt_decoder_destroy)

        self.frame_buffer = ffi.new('int16_t[]', self.frame_size)

    def decode(self, compressed):
        celt_call_errret('celt_decode', self.decoder, compressed,
                         len(compressed), self.frame_buffer)
        return bytes(ffi.buffer(ffi.cast('char*', self.frame_buffer),
                                self.frame_size * 2))


class Encoder(object):
    def __init__(self, rate, frame_size=None, channels=1):
        if frame_size is None:
            frame_size = rate // 100

        self.rate = rate
        self.frame_size = frame_size
        self.channels = channels

        self.mode = create_mode(self.rate, self.frame_size)
        self.encoder = ffi.gc(
            celt_call_errout('celt_encoder_create', self.mode, self.channels),
            libcelt.celt_encoder_destroy)

    def encode(self, pcm, size):
        compressed = ffi.new('char[]', size)

        n = libcelt.celt_encode(
            self.encoder, ffi.cast('int16_t*', ffi.new('char[]', pcm)),
            ffi.cast('int16_t*', 0), compressed, size)

        if n < 0:
            celt_check_error('celt_encode', n)

        return bytes(ffi.buffer(compressed, n))


class Codec(object):
    def __init__(self, rate, frame_size=None, channels=1):
        self.encoder = Encoder(rate, frame_size, channels)
        self.decoder = Decoder(rate, frame_size, channels)
