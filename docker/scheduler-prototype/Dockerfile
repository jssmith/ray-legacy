# Docker image for use with Ray scheduler prototype

FROM ray-project/ray:deploy-conda

RUN pip install --upgrade pip
RUN pip install --ignore-installed \
    https://storage.googleapis.com/tensorflow/linux/cpu/tensorflow-0.11.0-cp27-none-linux_x86_64.whl
RUN pip install scipy
RUN apt-get -y install zlib1g-dev libjpeg-dev xvfb libav-tools xorg-dev python-opengl libsdl2-dev swig wget
RUN pip install gym[atari]

WORKDIR /tmp
RUN wget -nv https://github.com/google/or-tools/releases/download/v5.0/or-tools_python_examples_v5.0.3919.tar.gz && \
    tar -xzf or-tools_python_examples_v5.0.3919.tar.gz && \
    cd ortools_examples && \
    python setup.py install && \
    cd .. && \
    rm -rf ortools_examples or-tools_python_examples_v5.0.3919.tar.gz
WORKDIR /

RUN git clone https://github.com/jssmith/ray-scheduler-prototype scheduler-prototype
