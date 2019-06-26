"""
Forward model

Uses CGS (cm-g-s) units unless otherwise stated
"""
# TODO: Check if adjoint works properly over collision/changing the seperation area
# I'm pretty sure it won't, because those are discontinuous change that will make the cost function
# discontinuous. If it does work, I'm pretty sure the cost function will be noisy

from time import perf_counter
import os
from os.path import join

import h5py

import numpy as np

from matplotlib import tri
from matplotlib import pyplot as plt

import dolfin as dfn
# import ufl

import forms as frm
# import fluids
import constants
import functionals

from collision import detect_collision, set_collision
from misc import get_dynamic_fluid_props

# dfn.parameters['form_compiler']['optimize'] = True
# dfn.parameters['form_compiler']['cpp_optimize'] = True

def increment_forward(x0, x1, solid_props, fluid_props):
    """
    Returns the states at the next time x1 = (u1, v1, a1) of the forward model given x0.

    Parameters
    ----------
    x0 : tuple (u0, v0, a0) of dfn.Function
        Initial states for the forward model
    solid_props : dict
        A dictionary of solid properties
    fluid_props : dict
        A dictionary storing fluid properties.

    Returns
    -------
    tuple (u1, v1, a1) of dfn.Function
        The next state of the forward model
    info : dict
        A dictionary of additional info. These are some things that are computed during the solve
        that might be useful.
    """
    u0, v0, a0 = x0
    u1, v1, a1 = x1
    if u1 is None:
        u1 = dfn.Function(frm.vector_function_space)
    if v1 is None:
        v1 = dfn.Function(frm.vector_function_space)
    if a1 is None:
        a1 = dfn.Function(frm.vector_function_space)

    ## Update form coefficients
    frm.emod.vector()[:] = solid_props['elastic_modulus']
    frm.u0.assign(u0)
    frm.v0.assign(v0)
    frm.a0.assign(a0)
    info = frm.set_pressure(fluid_props)

    # ## Collision handling
    # verts_coll = detect_collision(frm.mesh, frm.vertex_marker, frm.omega_contact, frm.u0, frm.v0, frm.a0,
    #                               frm.vert_to_vdof)

    frm.u1.assign(u0)
    dfn.solve(frm.fu_nonlin == 0, frm.u1, bcs=frm.bc_base, J=frm.jac_fu_nonlin)
    u1.assign(frm.u1)

    v1.vector()[:] = frm.newmark_v(u1.vector(), u0.vector(), v0.vector(), a0.vector(), frm.dt)
    a1.vector()[:] = frm.newmark_a(u1.vector(), u0.vector(), v0.vector(), a0.vector(), frm.dt)

    return (u1, v1, a1), info

def forward(tspan, solid_props, fluid_props, h5path="tmp.h5", h5group='/', show_figure=False):
    """
    Solves the forward model over a time interval.

    Parameters
    ----------
    tspan : (2,) array_like of float
        The start time and end time of the simulation in seconds.
    solid_props : dict
        Should use this style of call in the future?
    fluid_props : dict
        A dictionary storing fluid properties.
    save_path : string
        Path to an hdf5 file where states will be appended.
    group : string
        An h5 group to save under
    show_figure : bool
        Determines whether to display figures of the solution or not.
    """
    ## Allocate functions for states
    u0 = dfn.Function(frm.vector_function_space)
    v0 = dfn.Function(frm.vector_function_space)
    a0 = dfn.Function(frm.vector_function_space)

    u1 = dfn.Function(frm.vector_function_space)
    v1 = dfn.Function(frm.vector_function_space)
    a1 = dfn.Function(frm.vector_function_space)

    ## Allocate a figure for plotting
    fig, axs = None, None
    if show_figure:
        gridspec_kw = {'height_ratios': [3, 1]}
        fig, axs = plt.subplots(2, 1, gridspec_kw=gridspec_kw)
        axs[0].set_aspect('equal', adjustable='datalim')

        x = np.arange(frm.surface_vertices.shape[0])
        y = np.arange(frm.surface_vertices.shape[0])
        pressure_profile, = axs[1].plot(x, y, marker='o')

    elastic_modulus = solid_props['elastic_modulus']
    frm.emod.vector()[:] = elastic_modulus

    assert tspan[1] > tspan[0]
    dt = frm.dt.values()[0]
    num_time = np.ceil((tspan[1]-tspan[0])/dt)
    time = dt*np.arange(num_time)

    with h5py.File(h5path, mode='a') as f:
        for data, dataset_name in zip([u0, v0, a0], ['u', 'v', 'a']):
            f.create_dataset(join(h5group, dataset_name), shape=(num_time, data.vector()[:].size),
                             dtype=np.float64)
            f[join(h5group, dataset_name)][0] = data.vector()
        f.create_dataset(join(h5group, 'cost'), shape=(num_time-1,), dtype=np.float64)
        f.create_dataset(join(h5group, 'time'), data=time)
        f.create_dataset(join(h5group, 'vocal_efficiency'), shape=(num_time-1,), dtype=np.float64)
        f.create_dataset(join(h5group, 'fluid_work'), shape=(num_time-1,), dtype=np.float64)

    for ii, t in enumerate(time[:-1]):
        _fluid_props = get_dynamic_fluid_props(fluid_props, t)

        (u1, v1, a1), info = increment_forward([u0, v0, a0], [u1, v1, a1], solid_props, _fluid_props)

        xy_min = info['xy_min']
        xy_sep = info['xy_sep']
        flow_rate = info['flow_rate']

        ## Write the solution to a file
        with h5py.File(h5path, mode='a') as f:
            f[join(h5group, 'u')][ii+1] = u1.vector()[:]
            f[join(h5group, 'v')][ii+1] = v1.vector()[:]
            f[join(h5group, 'a')][ii+1] = a1.vector()[:]
            frm.u1.assign(u1)
            p_sub = _fluid_props['p_sub']

            # f['cost'][ii] = dfn.assemble(functionals.frm_fluidwork)
            vocal_efficiency = dfn.assemble(functionals.frm_fluidwork)/(flow_rate*p_sub*dt)
            f[join(h5group, 'cost')][ii] = vocal_efficiency

            f[join(h5group, 'fluid_work')][ii] = dfn.assemble(functionals.frm_fluidwork)
            f[join(h5group, 'vocal_efficiency')][ii] = vocal_efficiency

        ## Update initial conditions for the next time step
        u0.assign(u1)
        v0.assign(v1)
        a0.assign(a1)

        ## Plot the solution
        if show_figure:
            delta_xy = u0.vector()[frm.vert_to_vdof.reshape(-1)].reshape(-1, 2)
            xy_current = frm.mesh.coordinates() + delta_xy
            triangulation = tri.Triangulation(xy_current[:, 0], xy_current[:, 1],
                                              triangles=frm.mesh.cells())

            axs[0].clear()

            axs[0].triplot(triangulation)

            xy_surface = xy_current[frm.surface_vertices]

            axs[0].plot(*xy_min, marker='o', mfc='none', color='C0')
            axs[0].plot(*xy_sep, marker='o', mfc='none', color='C1')
            axs[0].plot(xy_surface[:, 0], xy_surface[:, 1], color='C3')
            axs[0].axhline(y=frm.y_midline, ls='-.')
            axs[0].axhline(y=frm.y_midline-frm.collision_eps, ls='-.', lw=0.5)

            axs[0].set_title(f'Time: {1e3*t:>5.1f} ms')

            pressure_profile.set_data(xy_surface[:, 0], info['pressure'])

            # Formatting
            axs[0].set_xlim(-0.1, frm.thickness_bottom+0.1, auto=False)
            axs[0].set_ylim(0.0, 0.7, auto=False)

            axs[1].set_xlim(-0.1, frm.thickness_bottom+0.1, auto=False)
            axs[1].set_ylim(0, 5*_fluid_props['p_sub'], auto=False)

            axs[1].set_ylabel('Surface pressure')
            plt.pause(0.001)

    total_cost = None
    with h5py.File(h5path, mode='r') as f:
        total_cost = np.sum(f[join(h5group, 'cost')][:])
    return total_cost

if __name__ == '__main__':
    dfn.set_log_level(30)
    emod = frm.emod.vector()[:].copy()
    solid_props = {'elastic_modulus': 2*emod}
    fluid_props = constants.DEFAULT_FLUID_PROPERTIES
    fluid_props['p_sub'] = [1800 * constants.PASCAL_TO_CGS, 1800 * constants.PASCAL_TO_CGS, 1, 1]
    fluid_props['p_sub_time'] = [0, 2.5e-3, 2.5e-3, 0.02]

    save_path = f"out/test.h5"
    try:
        os.remove(save_path)
    except FileNotFoundError:
        pass

    runtime_start = perf_counter()
    forward([0, 0.02], solid_props, fluid_props, save_path, show_figure=True)
    runtime_end = perf_counter()

    print(f"Runtime {runtime_end-runtime_start:.2f} seconds")
