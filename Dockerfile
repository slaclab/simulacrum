FROM ubuntu:20.04 as sim_builder
ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update && \
    apt-get -y install build-essential xterm man wget readline-common libreadline-dev sudo unzip \
                       cmake autoconf automake libtool m4 gfortran libtool-bin xorg xorg-dev bc \
                       libopenmpi-dev gfortran-multilib curl
WORKDIR /tmp
SHELL ["/bin/bash", "-c"]
RUN curl https://www.classe.cornell.edu/~cesrulib/downloads/tarballs/ | sed -n 's/.*href="\([^"]*\)\.tgz.*/\1/p' > /bmad_filename.txt
RUN curl https://www.classe.cornell.edu/~cesrulib/downloads/tarballs/$(cat /bmad_filename.txt).tgz > $(cat /bmad_filename.txt).tgz
WORKDIR /
RUN tar -xvf /tmp/$(cat /bmad_filename.txt).tgz -C /
RUN mv $(cat /bmad_filename.txt) bmad
COPY bmad_env.bash /bmad/bmad_env.bash
RUN ln -s /usr/bin/make /usr/bin/gmake
RUN cd /bmad && \
    pwd && \
    ls -la && \
    cmake --version && \
    source ./bmad_env.bash && \
    sed -i 's/ACC_ENABLE_SHARED.*/ACC_ENABLE_SHARED="Y"/' /bmad/util/dist_prefs && \
    sed -i 's/ACC_CMAKE_VERSION.*/ACC_CMAKE_VERSION=3\.16\.0/' /bmad/util/dist_env_vars && \
    sed -i 's/cpp_bmad_interface examples bsim util_programs lux regression_tests//' /bmad/util/Distribution_User_Utility_Wrapper

WORKDIR /bmad
RUN source ./bmad_env.bash && ./util/dist_build_production

FROM ubuntu:20.04
RUN apt-get update && apt-get -y install readline-common libreadline8 python3 python3-pip libzmq5 libx11-6 gfortran
RUN ln -s /usr/bin/python3 /usr/bin/python
RUN pip3 install numpy caproto pyzmq supervisor pexpect h5py
COPY model_service /model_service
COPY start_all_services.bash /start_all_services.bash
ENV TAO_LIB /tao/libtao.so
COPY --from=sim_builder /bmad/production/lib/libtao.so ${TAO_LIB}
COPY --from=sim_builder /bmad/tao/python/pytao /model_service/pytao
SHELL ["/bin/bash", "-c"]
COPY . /simulacrum
RUN cd /simulacrum && pip3 install . 
COPY bpm_service /bpm_service
COPY magnet_service /magnet_service
COPY camera_service /camera_service
COPY generic_pv_service /generic_pv_service
COPY klystron_service /klystron_service
COPY obstruct_service /obstruct_service
COPY undulator_service /undulator_service
COPY lcls-lattice /lcls-lattice
ENV LCLS_LATTICE /lcls-lattice
ENV MODEL_PORT 12312
ENV MODEL_BROADCAST_PORT 66666
ENV EPICS_CA_SERVER_PORT 5064
ENV EPICS_CA_REPEATER_PORT 5065
EXPOSE ${MODEL_PORT}
EXPOSE ${ORBIT_PORT}
EXPOSE ${EPICS_CA_SERVER_PORT}
#ENTRYPOINT cd /model_service && (python3 model_service.py &)
