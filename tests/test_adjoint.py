"""
Compare gradient computed via adjoint method with gradient computed via FD.
"""

import sys
import os
from time import perf_counter

import h5py
import dolfin as dfn
import matplotlib.pyplot as plt
import numpy as np

sys.path.append('../')
from femvf.forward import forward
from femvf.adjoint import adjoint
from femvf import forms
from femvf import constants
from femvf import functionals
from femvf import statefileutils as sfu

if __name__ == '__main__':
    dfn.set_log_level(30)

    ### Finite Differences
    print("Computing Gradient via Finite Differences")

    ## Mesh Setup
    mesh_dir = '../meshes'

    mesh_base_filename = 'geometry2'
    mesh_path = os.path.join(mesh_dir, mesh_base_filename + '.xml')

    model = forms.ForwardModel(mesh_path, {'pressure': 1, 'fixed': 3}, {})

    emod = model.emod.vector()[:].copy()
    emod[:] = 10e3 * constants.PASCAL_TO_CGS
    step_size = 0.01*constants.PASCAL_TO_CGS
    num_steps = 4

    # Set fluid and solid properties
    fluid_props = constants.DEFAULT_FLUID_PROPERTIES.copy()

    # Time varying fluid properties
    # fluid_props = constants.DEFAULT_FLUID_PROPERTIES
    # fluid_props['p_sub'] = [1500 * constants.PASCAL_TO_CGS, 1500 * constants.PASCAL_TO_CGS, 1, 1]
    # fluid_props['p_sub_time'] = [0, 3e-3, 3e-3, 0.02]

    solid_props = constants.DEFAULT_SOLID_PROPERTIES.copy()
    solid_props['rayleigh_m'] = 30
    solid_props['rayleigh_k'] = 1e-3

    dt = 1e-4
    times_meas = [0, 0.01]

    ## Running finite differences
    save_path = 'out/FiniteDifferenceStates.h5'
    with h5py.File(save_path, mode='w') as f:
        f.create_dataset('elastic_modulus', data=emod[0])
        f.create_dataset('step_size', data=step_size)
        f.create_dataset('num_steps', data=num_steps)

    for ii in range(num_steps):
        solid_props['elastic_modulus'] = emod + ii*step_size

        runtime_start = perf_counter()
        forward(model, 0, times_meas, dt, solid_props, fluid_props, h5file=save_path,
                h5group=f'{ii}/')
        runtime_end = perf_counter()

        print(f"Runtime {runtime_end-runtime_start:.2f} seconds")


    ### Adjoint
    print("Computing Gradient via Adjoint State")

    ## Different functional setups
    # Functional for vocal eff
    n_start = 50
    totalfluidwork = None
    totalinputwork = None
    with sfu.StateFile(save_path, group='0', mode='r') as f:
        totalfluidwork = functionals.totalfluidwork(model, f, n_start)[0]
        totalinputwork = functionals.totalinputwork(model, f, n_start)[0]
    fkwargs = {'n_start': n_start,
               'cache_totalfluidwork': totalfluidwork, 'cache_totalinputwork': totalinputwork}
    dg_du = functionals.dtotalvocaleff_du
    functional = functionals.totalvocaleff

    # Functional for MFDR
    # idx_mfdr = None
    # with sfu.StateFile(save_path, group='0', mode='r') as f:
    #     idx_mfdr = functionals.mfdr(model, f)[1]['idx_mfdr']
    # fkwargs = {'cache_idx_mfdr': idx_mfdr}
    # dg_du = functionals.dmfdr_du
    # functional = functionals.mfdr

    # Functional for weighted sum of squared glottal widths
    # fkwargs = {}
    # dg_du = functionals.dwss_gwidth_du
    # functional = functionals.wss_gwidth

    runtime_start = perf_counter()
    gradient = adjoint(model, save_path, h5group='0', dg_du=dg_du, dg_du_kwargs=fkwargs)
    runtime_end = perf_counter()

    print(f"Runtime {runtime_end-runtime_start:.2f} seconds")

    with h5py.File('out/Adjoint.h5', mode='w') as f:
        f.create_dataset('gradient', data=gradient)

    ### Comparing adjoint and finite differences
    # Load data and caculate gradient from FD steps
    emod = None
    cost_fd = list()
    with sfu.StateFile('out/FiniteDifferenceStates.h5', group=f'{ii}', mode='r') as f:
        # import ipdb; ipdb.set_trace()
        step_size = f.file['step_size'][()]
        num_steps = f.file['num_steps'][()]
        emod = f.file['elastic_modulus'] + np.arange(num_steps)*step_size
        for ii in range(num_steps):
            f.group = f'{ii}'
            cost_fd.append(functional(model, f, n_start)[0])

    # Load the gradient from the adjoint method
    grad_ad = None
    with h5py.File('out/Adjoint.h5', mode='r') as f:
        grad_ad = f['gradient'][...]

    ### Figure generation
    fig, axs = plt.subplots(1, 2, figsize=(7, 3))

    ## Plotting
    cost_fd = np.array(cost_fd)
    axs[0].plot(emod, cost_fd, color='C0', marker='o', label="Functional from F")

    # Project the gradient in the direction of uniform increase in elastic modulus
    demod = emod-emod[0]
    grad_ad_projected = grad_ad.sum()
    cost_ad = cost_fd[0] + grad_ad_projected*demod
    axs[0].plot(emod, cost_ad, color='C1', marker='o', label="Linear prediction from gradient")

    grad_fd_projected = (cost_fd[1:]-cost_fd[0])/(demod[1:])
    error = np.abs((grad_ad_projected-grad_fd_projected)/grad_ad_projected)*100
    axs[1].plot(np.arange(error.size)+1, error)

    ## Formatting
    axs[0].set_xlabel("Elastic modulus [Pa]")
    axs[0].set_ylabel("Objective function")
    axs[0].legend()

    axs[1].set_ylabel(r"% Error")

    for ax in axs:
        ax.grid()

    axs[0].set_xlabel(r"$E$")
    axs[1].set_xlabel(r"$N_{\Delta h}$")

    axs[0].set_xlim(emod[[0, -1]])
    axs[1].set_xlim([0, error.size])
    axs[1].set_ylim([0, error.max()])

    plt.tight_layout()
    plt.show()

    print(f"Linear gradient prediction {grad_ad_projected:.16e}")
    print(f"Actual FD values {grad_fd_projected[0]:.16e}")
    print(f"% Error {error}")
