"""
Adjoint model.

Makes a vocal fold go elggiw elggiw.

I'm using CGS : cm-g-s units
"""

from time import perf_counter

import numpy as np

from matplotlib import tri
from matplotlib import pyplot as plt

import h5py

import dolfin as dfn
import ufl

#import petsc4py
#petsc4py.init()
from petsc4py import PETSc

from . import forms as frm
# from . import linalg
from . import statefileutils as sfu
from . import constants
from . import functionals

# import forms as frm

from .misc import get_dynamic_fluid_props

# dfn.parameters['form_compiler']['optimize'] = True
# dfn.parameters['form_compiler']['cpp_optimize'] = True

dfu_dparam_form_adjoint = dfn.adjoint(ufl.derivative(frm.f1, frm.emod, frm.scalar_trial))

def decrement_adjoint(adj_x2, x0, x1, x2, dt1, dt2, solid_props, fluid_props0, fluid_props1, dcost_du1):
    """
    Returns the adjoint at the previous time step.

    Each adjoint step is based on an indexing scheme where the postfix on a variable represents that
    variable at time index n + postfix. For example, variables x0, x1, and x2 correspond to states
    at n, n+1, and n+2.

    This is done because the adjoint calculation to solve for :math:`lambda_{n+1}` given
    :math:`lambda_{n+2}` requires the forward equations :math:`f^{n+2}=0`, and :math:`f^{n+1}=0`, which in
    turn require states :math:`x^{n}`, :math:`x^{n+1}`, and :math:`x^{n+2}` to be defined.

    Note that :math:`f^{n+1} = f^{n+1}([u, v, a]^{n+1}, [u, v, a]^{n}) = 0` involves the FEM
    approximation and time stepping scheme that defines the state :math`x^{n+1} = (u, v, a)^{n+1}`
    implicitly, which could be linear or non-linear.

    Parameters
    ----------
    adj_x2 : tuple of dfn.Function
        A tuple (adj_u2, adj_v2, adj_a2) of 'initial' (time index 2) states for the adjoint model.
    x0, x1, x2 : tuple of dfn.Function
        Tuple (u, v, a) of states at time indices 0, 1, and 2.
    dt1, dt2 : float
        The timesteps associated with the f1 and f2 forward models respectively.
    solid_props : dict
        A dictionary of solid properties.
    fluid_props0, fluid_props1 : dict
        Dictionaries storing fluid properties at time indices 0 and 1.
    h5path : string
        Path to an hdf5 file containing states from a forward run of the model.
    h5group : string
        The group where states are stored in the hdf5 file.

    Returns
    -------
    adj_x1 : tuple of dfn.Function
        The 'next' state (adj_u1, adj_v1, adj_a1) of the adjoint model.
    info : dict
        Additional info computed during the solve that might be useful.
    """
    adj_u2, adj_v2, adj_a2 = adj_x2

    ## Set form coefficients to represent f^{n+2} aka f2(x1, x2) -> x2
    frm.dt.assign(dt2)
    frm.u1.vector()[:] = x2[0]
    frm.u0.vector()[:], frm.v0.vector()[:], frm.a0.vector()[:] = x1
    frm.set_pressure(fluid_props1)
    dpressure_du0 = frm.set_flow_sensitivity(fluid_props1)[0]
    frm.emod.vector()[:] = solid_props['elastic_modulus']

    # Assemble needed forms
    df2_du1 = dfn.assemble(frm.df1_du0_adjoint)
    df2_dv1 = dfn.assemble(frm.df1_dv0_adjoint)
    df2_da1 = dfn.assemble(frm.df1_da0_adjoint)

    # Correct df2_du1 since pressure depends on u1 for explicit FSI forcing
    df2_dpressure = dfn.as_backend_type(dfn.assemble(frm.df1_dp_adjoint)).mat()
    df2_du1 = df2_du1 + dfn.Matrix(dfn.PETScMatrix(dpressure_du0.transposeMatMult(df2_dpressure)))

    ## Set form coefficients to represent f^{n+1} aka f1(x0, x1) -> x1
    frm.dt.assign(dt1)
    frm.u1.vector()[:] = x1[0]
    frm.u0.vector()[:], frm.v0.vector()[:], frm.a0.vector()[:] = x0
    frm.set_pressure(fluid_props0)
    frm.emod.vector()[:] = solid_props['elastic_modulus']

    # Assemble needed forms
    df1_du1 = dfn.assemble(frm.df1_du1_adjoint)
    df1_dparam = dfn.assemble(dfu_dparam_form_adjoint)

    ## Adjoint recurrence relations
    # Allocate adjoint states
    adj_u1 = dfn.Function(frm.vector_function_space)
    adj_v1 = dfn.Function(frm.vector_function_space)
    adj_a1 = dfn.Function(frm.vector_function_space)

    # You probably don't need to set Dirichlet BCs on adj_a or adj_v because they are always zeroed
    # out when solving for adj_u (but I'm gonna do it anyway)
    gamma, beta = frm.gamma.values()[0], frm.beta.values()[0]

    # These are manually implemented matrix multiplications representing adjoint recurrence 
    # relations
    # TODO: you can probably take advantage of autodiff capabilities of fenics of the newmark
    # schemes so you don't have to do the differentiation manually like you did here.
    adj_a1.vector()[:] = -1 * (df2_da1 * adj_u2.vector()
                               + dt2 * (gamma/2/beta-1) * adj_v2.vector()
                               + (1/2/beta-1) * adj_a2.vector())
    frm.bc_base_adjoint.apply(adj_a1.vector())

    adj_v1.vector()[:] = -1 * (df2_dv1 * adj_u2.vector()
                               + (gamma/beta-1) * adj_v2.vector()
                               + 1/beta/dt2 * adj_a2.vector())
    frm.bc_base_adjoint.apply(adj_v1.vector())

    adj_u1_lhs = dcost_du1 \
                 + gamma/beta/dt1 * adj_v1.vector() + 1/beta/dt1**2 * adj_a1.vector() \
                 - (df2_du1 * adj_u2.vector()
                    + gamma/beta/dt2 * adj_v2.vector()
                    + 1/beta/dt2**2 * adj_a2.vector())
    frm.bc_base_adjoint.apply(df1_du1, adj_u1_lhs)
    dfn.solve(df1_du1, adj_u1.vector(), adj_u1_lhs)

    return (adj_u1, adj_v1, adj_a1), df1_dparam

def adjoint(h5file, h5group='/', show_figure=False,
            dg_du=functionals.dtotalvocaleff_du, dg_du_kwargs={}):
    """
    Returns the gradient of the cost function w.r.t elastic modulus using the adjoint model.

    TODO: Remove the solid_props parameter. This should be retrievable from the h5file.

    Parameters
    ----------
    h5file : string
        Path to an hdf5 file containing states from a forward run of the model.
    h5group : string
        The group where states are stored in the hdf5 file.
    show_figures : bool
        Whether to display a figure showing the solution or not.
    dg_du : callable
        A callable returning the sensitivity of a functional, g, with respect to the state n given.
        The signature should be dg_du(n, h5file, h5group='/', **kwargs)
    """
    ## Allocate adjoint states
    adj_u1 = dfn.Function(frm.vector_function_space)
    adj_v1 = dfn.Function(frm.vector_function_space)
    adj_a1 = dfn.Function(frm.vector_function_space)

    adj_u2 = dfn.Function(frm.vector_function_space)
    adj_v2 = dfn.Function(frm.vector_function_space)
    adj_a2 = dfn.Function(frm.vector_function_space)

    ## Allocate space for the gradient
    gradient = np.zeros(frm.emod.vector().size())

    times = None
    num_states = None
    with h5py.File(h5file, mode='r') as f:
        times = sfu.get_times(f, group=h5group)
        num_states = sfu.get_num_states(f, group=h5group)

    # Set form coefficients to represent f^{N-1} (the final forward increment model that solves
    # for the final state)
    fluid_props, solid_props, x1, x2 = None, None, None, None
    with h5py.File(h5file, mode='r') as f:
        fluid_props = sfu.get_fluid_properties(num_states-2, f, group=h5group)
        solid_props = sfu.get_solid_properties(f, group=h5group)
        frm.emod.vector()[:] = solid_props['elastic_modulus']
        x2 = sfu.get_state(num_states-1, f, group=h5group)
        x1 = sfu.get_state(num_states-2, f, group=h5group)

    frm.dt.assign(times[-1]-times[-2])
    frm.u1.vector()[:] = x2[0]
    frm.u0.vector()[:], frm.v0.vector()[:], frm.a0.vector()[:] = x1
    frm.set_pressure(fluid_props)

    df2_du2 = dfn.assemble(frm.df1_du1_adjoint)
    # import ipdb; ipdb.set_trace()

    ## Initialize the adjoint state
    dcost_du2 = None
    with h5py.File(h5file, mode='r') as f:
        dcost_du2 = dg_du(num_states-1, f, h5group=h5group, **dg_du_kwargs)[0]

    frm.bc_base_adjoint.apply(df2_du2, dcost_du2)
    dfn.solve(df2_du2, adj_u2.vector(), dcost_du2)
    adj_v2.vector()[:] = 0
    adj_a2.vector()[:] = 0

    df2_dparam = dfn.assemble(dfu_dparam_form_adjoint)
    gradient += -1*df2_dparam*adj_u2.vector() + 0

    ## Loop through states for adjoint computation
    with h5py.File(h5file, mode='r') as f:
        for ii in range(num_states-2, 0, -1):
            # Note that ii corresponds to the time index of the adjoint state we are solving for.
            # In a given loop, adj^{ii+1} is known, and the iteration of the loop finds adj^{ii}
            x0 = sfu.get_state(ii-1, f, group=h5group)
            x1 = sfu.get_state(ii, f, group=h5group)
            x2 = sfu.get_state(ii+1, f, group=h5group)

            fluid_props0 = sfu.get_fluid_properties(ii-1, f, group=h5group)
            fluid_props1 = sfu.get_fluid_properties(ii, f, group=h5group)
            
            dt1 = times[ii] - times[ii-1]
            dt2 = times[ii+1] - times[ii]

            dcost_du1 = dg_du(ii, f, h5group=h5group, **dg_du_kwargs)[0]

            (adj_u1, adj_v1, adj_a1), df1_dparam = decrement_adjoint(
                (adj_u2, adj_v2, adj_a2), x0, x1, x2, dt1, dt2, solid_props, 
                 fluid_props0, fluid_props1, dcost_du1)

            # Update gradient using the adjoint state
            # TODO: Here we assumed that functionals never depend on the velocity or acceleration
            # states so we only multiply by adj_u1. In the future you might have to use adj_v1 and 
            # adj_a1 too.
            gradient = gradient - 1*df1_dparam*adj_u1.vector()

            # Update adjoint recurrence relations for the next iteration
            adj_a2.assign(adj_a1)
            adj_v2.assign(adj_v1)
            adj_u2.assign(adj_u1)

    ## Plot the gradient
    if show_figure:
        fig, ax = plt.subplots(1, 1)

        ax.set_aspect('equal')
        coords = frm.mesh.coordinates()[...]
        triangulation = tri.Triangulation(coords[:, 0], coords[:, 1], triangles=frm.mesh.cells())

        ax.set_xlim(-0.1, 0.7, auto=False)
        ax.set_ylim(-0.1, 0.7)

        ax.axhline(y=frm.y_midline, ls='-.')
        ax.axhline(y=frm.y_midline-frm.collision_eps, ls='-.', lw=0.5)

        ax.set_title('Gradient')

        mappable = ax.tripcolor(triangulation, gradient[frm.vert_to_sdof],
                                edgecolors='k', shading='flat')
        coords_fixed = frm.mesh.coordinates()[frm.fixed_vertices]
        ax.plot(coords_fixed[:, 0], coords_fixed[:, 1], color='C1')

        fig.colorbar(mappable, ax=ax)

        plt.show()

    return gradient

if __name__ == '__main__':
    input_path = 'out/test.h5'

    fluid_props = constants.DEFAULT_FLUID_PROPERTIES
    solid_props = {'elastic_modulus': frm.emod.vector()}

    runtime_start = perf_counter()
    gradient = adjoint(solid_props, input_path)
    runtime_end = perf_counter()
    print(f"Runtime {runtime_end-runtime_start:.2f} seconds")

    with h5py.File('out/adjoint.h5', mode='w') as f:
        f.create_dataset('gradient', data=gradient)
