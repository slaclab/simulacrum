FROM ubuntu:18.04 as sim_builder
ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update && \
    apt-get -y install build-essential libssl-dev xterm man wget readline-common libreadline-dev sudo unzip \
                       autoconf automake libtool m4 gfortran libtool-bin xorg xorg-dev bc \
                       libopenmpi-dev gfortran-multilib curl
RUN wget https://cmake.org/files/v3.18/cmake-3.18.4.tar.gz && tar -xvzf cmake-3.18.4.tar.gz
WORKDIR ./cmake-3.18.4
RUN ./bootstrap && make && make install
WORKDIR /tmp
SHELL ["/bin/bash", "-c"]
RUN curl https://www.classe.cornell.edu/~cesrulib/downloads/tarballs/ | sed -n 's/.*href="\([^"]*\)\.tgz.*/\1/p' > /bmad_filename.txt
RUN wget -nv "https://www.classe.cornell.edu/~cesrulib/downloads/tarballs/$(cat /bmad_filename.txt).tgz"
WORKDIR /
RUN tar -xvf /tmp/$(cat /bmad_filename.txt).tgz -C /
RUN mv $(cat /bmad_filename.txt) bmad
COPY bmad_env.bash /bmad/bmad_env.bash
RUN ln -s /usr/bin/make /usr/bin/gmake
RUN cd /bmad && \
    pwd && \
    ls -la && \
    source ./bmad_env.bash && \
    sed -i 's/ACC_ENABLE_OPENMP.*/ACC_ENABLE_OPENMP="Y"/' /bmad/util/dist_prefs && \
    sed -i 's/ACC_ENABLE_MPI.*/ACC_ENABLE_MPI="Y"/' /bmad/util/dist_prefs && \
    sed -i 's/ACC_ENABLE_SHARED.*/ACC_ENABLE_SHARED="Y"/' /bmad/util/dist_prefs && \
    sed -i 's/ACC_ENABLE_MPI.*/ACC_ENABLE_MPI="Y"/' /bmad/util/dist_prefs && \
    sed -i 's:CMAKE_Fortran_COMPILER\} MATCHES "ifort":CMAKE_Fortran_COMPILER\} STREQUAL "ifort":' /bmad/build_system/Master.cmake && \
    sed -i '/export PACKAGE_VERSION=/a source .\/VERSION' /bmad/openmpi/acc_build_openmpi

WORKDIR /bmad
RUN apt-get -y install libpango1.0-dev
RUN source ./bmad_env.bash && ./util/dist_build_production

FROM ubuntu:18.04
RUN apt-get update && apt-get -y install readline-common python3 python3-pip libzmq5 libx11-6 gfortran libpango1.0-dev
RUN ln -s /usr/bin/python3 /usr/bin/python
RUN pip3 install numpy caproto pyzmq
COPY model_service /model_service
COPY start_all_services.bash /start_all_services.bash
ENV TAO_LIB /tao/libtao.so
COPY --from=sim_builder /bmad/production/lib/libtao.so ${TAO_LIB}
# COPY --from=sim_builder /bmad/tao/python/pytao /model_service/pytao
RUN pip3 install pytao pyepics
SHELL ["/bin/bash", "-c"]
COPY . /simulacrum
RUN cd /simulacrum && pip3 install . 
COPY bpm_service /bpm_service
COPY magnet_service /magnet_service
RUN apt-get -y install git
RUN git clone https://github.com/slaclab/lcls-tools.git && cd ./lcls-tools && python3 setup.py install
RUN cd / && git clone https://github.com/slaclab/lcls-classic-lattice.git 
ENV MODEL_PORT 12312
ENV ORBIT_PORT 56789
ENV EPICS_CA_SERVER_PORT 5064
ENV EPICS_CA_REPEATER_PORT 5065
ENV LCLS_CLASSIC_LATTICE /lcls-classic-lattice
EXPOSE ${MODEL_PORT}
EXPOSE ${ORBIT_PORT}
EXPOSE ${EPICS_CA_SERVER_PORT}
#ENTRYPOINT cd /model_service && (python3 model_service.py &)
