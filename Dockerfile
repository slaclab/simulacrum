FROM ubuntu:18.04 as sim_builder
ENV DEBIAN_FRONTEND noninteractive
### APT GET DEPENDENCIES FOR BMAD/TAO BUILD
RUN apt-get update && \
    apt-get -y install build-essential libssl-dev xterm man wget readline-common libreadline-dev sudo unzip \
                       autoconf automake libtool m4 gfortran libtool-bin xorg xorg-dev bc \
                       libopenmpi-dev gfortran-multilib curl libpango1.0-dev git 
### BUILD CMAKE FROM SOURCE
RUN wget https://cmake.org/files/v3.18/cmake-3.18.4.tar.gz && tar -xvzf cmake-3.18.4.tar.gz
WORKDIR ./cmake-3.18.4
RUN ./bootstrap && make && make install
### CLEAN UP CMAKE TO SAVE SPACE
RUN cd / && rm -rf cmake-3.18.4
### BMAD/TAO DOWNLOAD
SHELL ["/bin/bash", "-c"]
WORKDIR /tmp
RUN git clone --branch main https://github.com/bmad-sim/bmad-ecosystem.git
WORKDIR /tmp/bmad-ecosystem
# Fetch all tags and checkout the most recent tag available
RUN git fetch --tags
RUN export bmad_release=$(git describe --tags `git rev-list --tags --max-count=1`) && \
    wget https://github.com/bmad-sim/bmad-ecosystem/releases/download/${bmad_release}/bmad_dist.tar.gz 
### BMAD/TAO EXTRACTION
WORKDIR /
RUN tar -xvf /tmp/bmad-ecosystem/bmad_dist.tar.gz -C /
RUN rm -rf /tmp/bmad-ecosystem && mv bmad_dist_* bmad

### BMAD/TAO CONFIGURATION
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
    sed -i 's:CMAKE_Fortran_COMPILER\} MATCHES "ifort":CMAKE_Fortran_COMPILER\} STREQUAL "ifort":' /bmad/util/Master.cmake && \
    sed -i '/export PACKAGE_VERSION=/a source .\/VERSION' /bmad/openmpi/acc_build_openmpi

### BMAD/TAO BUILD
WORKDIR /bmad
RUN source ./bmad_env.bash && ./util/dist_build_production


FROM ubuntu:18.04
### APT GET DEPENDENCIES FOR SIMULACRUM SERVICES
RUN apt-get update && apt-get -y install readline-common python3 python3-pip libzmq5 libx11-6 gfortran libpango1.0-dev git
RUN ln -s /usr/bin/python3 /usr/bin/python
### INSTALL PYTHON PACKAGES USING PIP AND GIT
RUN pip3 install numpy caproto pyzmq pytao pyepics scipy
RUN git clone https://github.com/slaclab/lcls-tools.git && cd ./lcls-tools && python3 setup.py install
RUN cd / && git clone https://github.com/slaclab/lcls-classic-lattice.git
### COPY OVER ANY SERVICES/SCRIPTS FROM SIMULACRUM REPO
COPY model_service /model_service
COPY start_all_services.bash /start_all_services.bash
COPY bpm_service /bpm_service
COPY magnet_service /magnet_service
COPY --from=sim_builder /bmad/production/lib/libtao.so /tao/${TAO_LIB}
COPY . /simulacrum
### SETUP FOR SIMULACRUM
ENV TAO_LIB /tao/libtao.so
# COPY --from=sim_builder /bmad/tao/python/pytao /model_service/pytao
SHELL ["/bin/bash", "-c"]
RUN cd /simulacrum && pip3 install . 
ENV MODEL_PORT 12312
ENV ORBIT_PORT 56789
ENV EPICS_CA_SERVER_PORT 5064
ENV EPICS_CA_REPEATER_PORT 5065
ENV LCLS_CLASSIC_LATTICE /lcls-classic-lattice
EXPOSE ${MODEL_PORT}
EXPOSE ${ORBIT_PORT}
EXPOSE ${EPICS_CA_SERVER_PORT}
#ENTRYPOINT cd /model_service && (python3 model_service.py &)
