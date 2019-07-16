#!/bin/bash
SIMUL_ROOT=/afs/slac/g/ad/simul
pushd ${SIMUL_ROOT}
source ./ENV
export DIST_BASE_DIR=/nfs/slac/g/beamphysics/cmayes/mcc-simul/devel
export PYTHONPATH=$PYTHONPATH:$DIST_BASE_DIR/tao/python
source ${DIST_BASE_DIR}/util/dist_source_me
ulimit -S -c 0
ulimit -S -d 25165824
popd
