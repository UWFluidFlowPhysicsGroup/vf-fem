"""
Compare gradient computed via adjoint method with gradient computed via FD.
"""

import sys
from time import perf_counter

import h5py
import dolfin as dfn

sys.path.append('../')
from femvf.forward import forward
from femvf.adjoint import adjoint
from femvf import forms as frm
from femvf import constants
from femvf import functionals

if __name__ == '__main__':
    dfn.set_log_level(30)
    ## Running finite differences
    print("Computing FD")
    emod = frm.emod.vector()[:].copy()

    # Constant fluid properties
    # fluid_props = constants.DEFAULT_FLUID_PROPERTIES
    dt = 1e-4

    # Time varying fluid properties
    fluid_props = constants.DEFAULT_FLUID_PROPERTIES
    fluid_props['p_sub'] = [1500 * constants.PASCAL_TO_CGS, 1500 * constants.PASCAL_TO_CGS, 1, 1]
    fluid_props['p_sub_time'] = [0, 3e-3, 3e-3, 0.02]

    step_size = 0.1*constants.PASCAL_TO_CGS
    num_steps = 3

    save_path = 'out/FiniteDifferenceStates.h5'
    with h5py.File(save_path, mode='w') as f:
        f.create_dataset('elastic_modulus', data=emod[0])
        f.create_dataset('step_size', data=step_size)
        f.create_dataset('num_steps', data=num_steps)

    for ii in range(num_steps):
        tspan = [0, 0.01]
        solid_props = {'elastic_modulus': emod + ii*step_size}

        runtime_start = perf_counter()
        forward(tspan, dt, solid_props, fluid_props, h5file=save_path, h5group=f'{ii}/',
                show_figure=False)
        runtime_end = perf_counter()

        print(f"Runtime {runtime_end-runtime_start:.2f} seconds")

    ## Running adjoint
    print("Computing Adjoint")

    # Functional for vocal eff
    # totalfluidwork = None
    # totalinputwork = None
    # with h5py.File(save_path, mode='r') as f:
    #     totalfluidwork = functionals.totalfluidwork(0, f, h5group='0')
    #     totalinputwork = functionals.totalinputwork(0, f, h5group='0')
    # fkwargs = {'cache_totalfluidwork': totalfluidwork, 'cache_totalinputwork': totalinputwork}
    # dg_du = functionals.dtotalvocaleff_du

    # Functional for MFDR
    idx_mfdr = None
    with h5py.File(save_path, mode='r') as f:
        idx_mfdr = functionals.mfdr(0, f, h5group='0')[1]['idx_mfdr']
    fkwargs = {'cache_idx_mfdr': idx_mfdr}
    dg_du = functionals.dmfdr_du

    solid_props = {'elastic_modulus': emod}
    runtime_start = perf_counter()
    gradient = adjoint(solid_props, save_path, h5group='0', dg_du=dg_du, dg_du_kwargs=fkwargs)
    runtime_end = perf_counter()

    print(f"Runtime {runtime_end-runtime_start:.2f} seconds")

    save_path = 'out/Adjoint.h5'
    with h5py.File(save_path, mode='w') as f:
        f.create_dataset('gradient', data=gradient)
