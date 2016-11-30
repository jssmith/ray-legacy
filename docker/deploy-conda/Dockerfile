# The deploy Docker image build a self-contained Ray instance suitable
# for end users.

FROM ubuntu:xenial
RUN apt-get update
RUN apt-get -y install apt-utils
RUN apt-get -y install vim wget
RUN apt-get -y install git cmake build-essential autoconf curl libtool libboost-all-dev unzip graphviz
RUN echo 'export PATH=/opt/conda/bin:$PATH' > /etc/profile.d/conda.sh && \
    wget --quiet https://repo.continuum.io/archive/Anaconda2-4.1.1-Linux-x86_64.sh -O /tmp/anaconda.sh && \
    /bin/bash /tmp/anaconda.sh -b -p /opt/conda && \
    rm /tmp/anaconda.sh
ENV PATH /opt/conda/bin:$PATH
RUN pip install ipython funcsigs subprocess32 protobuf colorama graphviz simplejson
RUN pip install --upgrade git+git://github.com/cloudpipe/cloudpickle.git@0d225a4695f1f65ae1cbb2e0bbc145e10167cce4  # We use the latest version of cloudpickle because it can serialize named tuples.
ADD ray.tar /ray
WORKDIR /ray
RUN ./setup.sh
RUN ./build.sh
RUN echo '\n# Ray environment\nsource /ray/setup-env.sh' >> /root/.bashrc
ENTRYPOINT bash
