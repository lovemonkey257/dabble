FROM debian:12
WORKDIR /builder
RUN apt update && \
    apt install -y software-properties-common build-essential cmake

RUN apt-add-repository contrib non-free && \
    apt update && \
    apt install -y libmpg123-dev libfaad-dev libsdl2-dev libfdk-aac-dev \
                   libfftw3-dev libsndfile1-dev libsamplerate0-dev librtlsdr-dev libboost-dev jq

# Build dablin: /builder/dablin/build/src/dablin
RUN git clone https://github.com/lovemonkey257/dablin.git  && \
    cd dablin && \
    mkdir build && \
    cd build && \
    cmake .. && \
    make dablin

# Build eti-cmdline: /builder/eti-stuff/eti-cmdline/build/eti-cmdline-rtlsdr
RUN git clone https://github.com/lovemonkey257/eti-stuff.git && \
    cd eti-stuff/eti-cmdline
    mkdir build && \
    cd build && \
    cmake .. -DRTLSDR && \
    make

FROM python:3.11.14-slim
COPY --from=0 /builder/dablin/build/src/dablin /usr/bin/dablin
COPY --from=0 /builder/eti-stuff/eti-cmdline/build/eti-cmdline-rtlsdr /usr/bin/eti-cmdline-rtlsdr
RUN apt update && \
    apt install -y librtlsdr-dev python3-dev python3-alsaaudio python3-pyaudio
WORKDIR /app
RUN git clone https://github.com/lovemonkey257/dabble.git && \
    cd dabble && \
    pip install --no-cache-dir -r requirements.txt
CMD [ "python", "radio.py" ]
