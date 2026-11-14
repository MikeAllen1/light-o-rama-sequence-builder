#!/bin/sh
# Build a small LGPL FFmpeg for the macOS app: it reads every song format the program
# accepts (MP3, M4A/AAC/ALAC, WAV, FLAC, OGG/Opus, WMA, AIFF, MKA) and writes WAV, and
# nothing else (no network, no video, no GPL parts). No FFmpeg build for macOS is
# published under the LGPL with a fixed checksum, so it is built from the release tag.
#   packaging/macos/build_ffmpeg.sh <FFmpeg source folder> <install folder>
set -eu
src="$1"; prefix="$2"
cd "$src"
./configure --prefix="$prefix" \
  --disable-everything --disable-autodetect --disable-network --disable-doc \
  --disable-ffplay --disable-ffprobe --disable-avdevice --disable-swscale --disable-postproc \
  --disable-debug --enable-small \
  --enable-protocol=file,pipe \
  --enable-demuxer=wav,mp3,aac,flac,ogg,asf,aiff,mov,matroska \
  --enable-parser=aac,mpegaudio,flac,opus,vorbis \
  --enable-decoder=mp3,mp3float,mp2,mp2float,aac,aac_fixed,alac,flac,vorbis,opus,wmav1,wmav2,wmapro,wmalossless,pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_s32be,pcm_f32le,pcm_f32be,pcm_f64le,pcm_u8,pcm_alaw,pcm_mulaw,adpcm_ima_wav,adpcm_ms \
  --enable-encoder=pcm_s16le --enable-muxer=wav \
  --enable-filter=aresample,aformat,anull,atrim,format,null \
  --enable-swresample
make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"
make install
