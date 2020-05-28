"""
Forward model

Uses CGS (cm-g-s) units unless otherwise stated
"""

from math import isclose, ceil, floor, remainder

import numpy as np
from matplotlib import pyplot as plt
import dolfin as dfn

from . import solids
from . import statefile as sf
from . import vis

# from .collision import detect_collision
from .misc import get_dynamic_fluid_props

DEFAULT_NEWTON_SOLVER_PRM = {'linear_solver': 'petsc', 'absolute_tolerance': 1e-8, 'relative_tolerance': 1e-10}
FIXEDPOINT_SOLVER_PRM = {'absolute_tolerance': 1e-8, 'relative_tolerance': 1e-11}

def integrate_adaptive(model, uva, solid_props, fluid_props, timing_props,
            h5file='tmp.h5', h5group='/',
            adaptive_step_prm=None, newton_solver_prm=None, show_figure=False, figure_path=None):
    """
    Solves the forward model over specific time instants.

    The `model` is solved over specific time instants. All intermediate solution states are saved to
    an hdf5 file.

    Parameters
    ----------
    model : model.ForwardModel
        An object representing the forward model.
    uva : tuple of array_like or float
        Initial solid state (u, v, a)
    qp : tuple of array_like or float
        Initial fluid state (q, p)
    timing_props : properties.TimingProperties
        A timing properties object
    solid_props : properties.SolidProperties
        A solid properties object
    fluid_props : properties.FluidProperties
        A fluid properties object
    h5file : string
        Path to an hdf5 file where solution information will be appended.
    h5group : string
        A group in the h5 file to save solution information under.
    adaptive_step_prm : dict of {'abs_tol': float or None, 'abs_tol_bounds': tuple}
        A desired tolerance that the norm of the displacement solution should meet
        Bounds on the solution norm tolerance. Time steps are adjusted so that the local error in
        :math:`u_{n+1}` is between `abs_tol_bounds[0]*abs_tol` and `abs_tol_bounds[1]*abs_tol`.
    show_figure : bool
        Determines whether to display figures of the solution or not.
    figure_path : string
        A path to save figures to. The figures will have a postfix of the iteration number and
        extension added.

    Returns
    -------
    info : dict
        A dictionary of info about the run.
    """
    # The default for adaptive time stepping is to not use it. Plus I think I messed up how it works
    if adaptive_step_prm is None:
        adaptive_step_prm = {'abs_tol': None, 'abs_tol_bounds': (0.0, 0.0)}
    info = {}

    t0, tmeas, dt_max = timing_props['t0'], timing_props['tmeas'], timing_props['dt_max']
    model.set_fluid_props(fluid_props)
    model.set_solid_props(solid_props)

    # Allocate functions for states
    u0 = dfn.Function(model.solid.vector_fspace).vector()
    v0 = dfn.Function(model.solid.vector_fspace).vector()
    a0 = dfn.Function(model.solid.vector_fspace).vector()
    u0[:], v0[:], a0[:] = uva

    model.set_ini_state(u0, v0, a0)

    q0, p0, info = model.get_pressure()
    model.set_pressure(p0)

    # TODO: This should be removed. If you want to calculate a functional to record
    # during the solution, a parameter should be made available in the function for that
    ## Record things of interest initial state
    idx_separation = []
    idx_min_area = []
    glottal_width = []
    flow_rate = []
    pressure = []
    glottal_width.append(info['a_min'])
    flow_rate.append(info['flow_rate'])

    ## Allocate a figure for plotting
    fig, axs = None, None
    if show_figure:
        fig, axs = vis.init_figure(model, fluid_props)

    # Get the solution times
    tmeas = np.array(tmeas)
    if tmeas[-1] < tmeas[0]:
        raise ValueError("The final solution time must be greater than the initial solution time."
                         f"The input intial/final times were {tmeas[0]}/{tmeas[-1]}")
    if tmeas.size <= 1:
        raise ValueError("There must be atleast 2 measured time instances.")

    ## Initialize datasets to save in h5 file
    with sf.StateFile(model, h5file, group=h5group, mode='a') as f:
        f.init_layout(uva0=(u0, v0, a0), qp0=(q0, p0),
                      fluid_props=fluid_props, solid_props=solid_props)
        f.append_time(t0)

    ## Loop through solution times and write solution variables to the h5file.
    # TODO: Hardcoded the calculation of glottal width here, but it should be an option you
    # can pass in along with other functionals of interest
    with sf.StateFile(model, h5file, group=h5group, mode='a') as f:
        t_current = t0
        n_state = 0

        for t_target in tmeas:
            # Keep incrementing until you reach the target time
            dt_proposal = dt_max
            while not isclose(t_current, t_target, rel_tol=1e-7, abs_tol=10*2**-52):
                assert t_current < t_target

                uva0 = (u0, v0, a0)
                qp0 = (q0, p0)

                # Increment the state using a target time step. If the previous time step was
                # refined to be smaller than the max time step, then try using that time step again.
                # If the local error is super low, the refinement time step will be predicted to be
                # high and so it will go back to the max time step.
                dt_target = min(dt_proposal, dt_max, t_target - t_current)
                uva1, qp1, dt_actual, step_info = adaptive_step(model, uva0, qp0, dt_target,
                                                                **adaptive_step_prm)
                n_state += 1
                t_current += dt_actual

                dt_proposal = dt_actual

                idx_separation.append(step_info['fluid_info']['idx_sep'])
                idx_min_area.append(step_info['fluid_info']['idx_min'])
                glottal_width.append(step_info['fluid_info']['a_min'])
                flow_rate.append(step_info['fluid_info']['flow_rate'])
                pressure.append(step_info['fluid_info']['pressure'])

                ## Write the solution outputs to a file
                f.append_time(t_current)
                f.append_state(uva1)
                f.append_fluid_state(qp1)

                ## Update initial conditions for the next time step
                u0[:] = uva1[0]
                v0[:] = uva1[1]
                a0[:] = uva1[2]
                q0 = qp1[0]
                p0 = qp1[1]

                ## Plot the solution
                if show_figure:
                    fig, axs = vis.update_figure(fig, axs, model, t_current, (u0, v0, a0),
                                                 step_info['fluid_info'],
                                                 solid_props, fluid_props)
                    plt.pause(0.001)

                    if figure_path is not None:
                        ext = '.png'
                        fig.savefig(f'{figure_path}_{n_state}{ext}')

            f.append_meas_index(n_state)

        # Write out the quantities fo interest to the h5file
        f.file[f'{h5group}/gaw'] = np.array(glottal_width)

        info['meas_ind'] = f.get_meas_indices()
        info['time'] = f.get_times()
        info['glottal_width'] = np.array(glottal_width)
        info['flow_rate'] = np.array(flow_rate)
        info['idx_separation'] = np.array(idx_separation)
        info['idx_min_area'] = np.array(idx_min_area)
        info['pressure'] = np.array(pressure)
        info['h5file'] = h5file
        info['h5group'] = h5group

    return info

def integrate(model, uva, solid_props, fluid_props, times, idx_meas=None,
                      h5file='tmp.h5', h5group='/', newton_solver_prm=None, coupling='implicit'):
    if idx_meas is None:
        idx_meas = np.array([])

    increment_forward = None
    if coupling == 'implicit':
        increment_forward = implicit_increment
    elif coupling == 'explicit':
        increment_forward = explicit_increment
    else:
        raise ValueError("`coupling` must be one of 'explicit' of 'implicit'")

    model.set_fluid_props(fluid_props)
    model.set_solid_props(solid_props)

    # Allocate functions to store states
    u0 = dfn.Function(model.solid.vector_fspace).vector()
    v0 = dfn.Function(model.solid.vector_fspace).vector()
    a0 = dfn.Function(model.solid.vector_fspace).vector()
    u0[:], v0[:], a0[:] = uva

    model.set_ini_state(u0, v0, a0)
    q0, p0, info = model.get_pressure()

    ## Record things of interest
    # TODO: This should be removed. If you want to calculate a functional to record
    # during the solution, a parameter should be made available in the function for that
    idx_separation = []
    idx_min_area = []
    glottal_width = []
    flow_rate = []
    pressure = []
    glottal_width.append(info['a_min'])
    flow_rate.append(info['flow_rate'])

    # Get the solution times
    if times[-1] < times[0]:
        raise ValueError("The final time point must be greater than the initial one."
                         f"The input intial/final times were {tmeas[0]}/{tmeas[-1]}")
    if times.size <= 1:
        raise ValueError("There must be atleast 2 time integration points.")

    ## Initialize datasets to save in h5 file
    with sf.StateFile(model, h5file, group=h5group, mode='a') as f:
        f.init_layout(uva0=(u0, v0, a0), qp0=(q0, p0), fluid_props=fluid_props, solid_props=solid_props)
        f.append_time(times[0])
        if 0 in idx_meas:
            f.append_meas_index(0)

    ## Loop through solution times and write solution variables to the h5file.
    # TODO: Hardcoded the calculation of glottal width here, but it should be an option you
    # can pass in along with other functionals of interest
    with sf.StateFile(model, h5file, group=h5group, mode='a') as f:
        for n in range(times.size-1):
            dt = times[n+1] - times[n]
            uva0 = (u0, v0, a0)
            qp0 = (q0, p0)

            # Increment the state
            uva1, qp1, step_info = None, None, None

            uva1, qp1, step_info = increment_forward(model, uva0, qp0, dt,
                                                     newton_solver_prm=newton_solver_prm)

            idx_separation.append(step_info['fluid_info']['idx_sep'])
            idx_min_area.append(step_info['fluid_info']['idx_min'])
            glottal_width.append(step_info['fluid_info']['a_min'])
            flow_rate.append(step_info['fluid_info']['flow_rate'])
            pressure.append(step_info['fluid_info']['pressure'])

            ## Write the solution outputs to a file
            f.append_state(uva1)
            f.append_fluid_state(qp1)
            f.append_time(times[n+1])
            if n+1 in idx_meas:
                f.append_meas_index(n+1)

            ## Update initial conditions for the next time step
            u0[:] = uva1[0]
            v0[:] = uva1[1]
            a0[:] = uva1[2]
            q0 = qp1[0]
            p0 = qp1[1]

        # Write out the quantities fo interest to the h5file
        f.file[f'{h5group}/gaw'] = np.array(glottal_width)

        info['meas_ind'] = f.get_meas_indices()
        info['time'] = f.get_times()
        info['glottal_width'] = np.array(glottal_width)
        info['flow_rate'] = np.array(flow_rate)
        info['idx_separation'] = np.array(idx_separation)
        info['idx_min_area'] = np.array(idx_min_area)
        info['pressure'] = np.array(pressure)
        info['h5file'] = h5file
        info['h5group'] = h5group

    return info

def explicit_increment(model, uva0, qp0, dt, newton_solver_prm=None):
    """
    Return the state at the end of `dt` `uva1 = (u1, v1, a1)`.

    Parameters
    ----------
    model : model.ForwardModel
    uva0 : tuple of dfn.Function
        Initial states (u0, v0, a0) for the forward model
    dt : float
        The time step to increment over
    solid_props : properties.SolidProperties, optional
        A dictionary of solid properties
    fluid_props : properties.FluidProperties, optional
        A dictionary of fluid properties.

    Returns
    -------
    tuple of dfn.Function
        The next state (u1, v1, a1) of the forward model
    tuple of (float, array_like)
        The next fluid state (q1, p1) of the forward model
    fluid_info : dict
        A dictionary containing information on the fluid solution. These include the flow rate,
        surface pressure, etc.
    """
    solid = model.solid
    u0, v0, a0 = uva0

    u1 = dfn.Function(solid.vector_fspace).vector()
    v1 = dfn.Function(solid.vector_fspace).vector()
    a1 = dfn.Function(solid.vector_fspace).vector()

    # Update form coefficients and initial guess
    model.set_iter_params(uva0=uva0, dt=dt, u1=u0, qp1=qp0)

    # TODO: You could implement this to use the non-linear solver only when collision is happening
    if newton_solver_prm is None:
        newton_solver_prm = DEFAULT_NEWTON_SOLVER_PRM

    dfn.solve(solid.f1 == 0, solid.u1, bcs=solid.bc_base, J=solid.df1_du1,
              solver_parameters={"newton_solver": newton_solver_prm})

    res = dfn.assemble(model.solid.forms['form.un.f1'])
    model.solid.bc_base.apply(res)

    u1[:] = solid.u1.vector()
    v1[:] = solids.newmark_v(u1, u0, v0, a0, dt)
    a1[:] = solids.newmark_a(u1, u0, v0, a0, dt)

    model.set_ini_state(u1, v1, a1)
    q1, p1, fluid_info = model.get_pressure()

    step_info = {'fluid_info': fluid_info}

    return (u1, v1, a1), (q1, p1), step_info

def implicit_increment(model, uva0, qp0, dt, newton_solver_prm=None):
    """
    Return the state at the end of `dt` `uva1 = (u1, v1, a1)`.

    Parameters
    ----------
    model : model.ForwardModel
    uva0 : tuple of dfn.Function
        Initial states (u0, v0, a0) for the forward model
    dt : float
        The time step to increment over
    solid_props : properties.SolidProperties, optional
        A dictionary of solid properties
    fluid_props : properties.FluidProperties, optional
        A dictionary of fluid properties.

    Returns
    -------
    tuple of dfn.Function
        The next state (u1, v1, a1) of the forward model
    tuple of (float, array_like)
        The next fluid state (q1, p1) of the forward model
    fluid_info : dict
        A dictionary containing information on the fluid solution. These include the flow rate,
        surface pressure, etc.
    """
    solid = model.solid
    u0, v0, a0 = uva0

    # Set initial guesses for the states at the next time
    u1 = dfn.Function(solid.vector_fspace).vector()
    v1 = dfn.Function(solid.vector_fspace).vector()
    a1 = dfn.Function(solid.vector_fspace).vector()

    u1[:] = u0
    q1, p1 = qp0

    # Solve the coupled problem using fixed point iterations between the fluid and solid
    if newton_solver_prm is None:
        newton_solver_prm = DEFAULT_NEWTON_SOLVER_PRM

    # calculate the initial residual
    model.set_iter_params(uva0=uva0, qp0=qp0, dt=dt, u1=u1, qp1=(q1, p1))
    res0 = dfn.assemble(model.solid.f1)
    model.solid.bc_base.apply(res0)

    # Set tolerances for the fixed point iterations
    nit = 0
    abs_tol, rel_tol = newton_solver_prm['absolute_tolerance'], newton_solver_prm['relative_tolerance']
    abs_err0, abs_err, rel_err = res0.norm('l2'), np.inf, np.inf
    while abs_err > abs_tol and rel_err > rel_tol:
        model.set_iter_params(uva0=uva0, qp0=qp0, dt=dt, u1=u1, qp1=(q1, p1))
        dfn.solve(solid.f1 == 0, solid.u1, bcs=solid.bc_base, J=solid.df1_du1,
                  solver_parameters={"newton_solver": newton_solver_prm})

        u1[:] = solid.u1.vector()
        v1[:] = solids.newmark_v(u1, u0, v0, a0, dt)
        a1[:] = solids.newmark_a(u1, u0, v0, a0, dt)

        # Set the state to calculate the pressure, but you have to set it back after
        model.set_ini_state(u1, v1, a1)
        q1, p1, fluid_info = model.get_pressure()

        # Calculate the error in the solid residual with the updated pressures
        model.set_iter_params(uva0=uva0, dt=dt, qp1=(q1, p1))
        res = dfn.assemble(solid.f1)
        solid.bc_base.apply(res)

        abs_err = res.norm('l2')
        rel_err = abs_err/abs_err0

        nit += 1

    model.set_iter_params(uva0=uva0, dt=dt, qp1=(q1, p1))
    res = dfn.assemble(model.solid.forms['form.un.f1'])
    model.solid.bc_base.apply(res)

    step_info = {'fluid_info': fluid_info,
                 'nit': nit, 'abs_err': abs_err, 'rel_err': rel_err}

    return (u1, v1, a1), (q1, p1), step_info

def adaptive_step(model, uva0, qp0, dt_max, abs_tol=1e-5, abs_tol_bounds=(0.8, 1.2)):
    """
    Integrate the model over `dt` using a smaller time step if needed.

    # TODO: `fluid_props` is assumed to be constant over the time step

    Parameters
    ----------
    model : model.ForwardModel
    uva0 : tuple of dfn.Function
        Initial states (u0, v0, a0) for the forward model.
    qp0 : tuple of fluid state variables
        (float, array_like) for Bernoulli
    dt_max : float
        The maximum time step to increment over.
    solid_props : dict
        A dictionary of solid properties.
    fluid_props : dict
        A dictionary of fluid properties.
    adaptive : bool
        Setting `adaptive=False` will enforce a single integration over the interval `dt`.

    Returns
    -------
    tuple(3 * dfn.Function)
        The states at the end of the time step.
    float
        The time step integrated over.
    fluid_info : dict
        A dictionary containing information on the fluid solution. These include the flow rate,
        surface pressure, etc.
    """
    uva1 = None
    dt = dt_max
    info = {}

    nrefine = -1
    refine = True
    while refine:
        nrefine += 1
        uva1, qp1, fluid_info = explicit_increment(model, uva0, qp0, dt)
        info['fluid_info'] = fluid_info

        err = newmark_error_estimate(uva1[2], uva0[2], dt, beta=model.forms['coeff.time.beta'].values()[0])
        err_norm = err.norm('l2')
        info['err_norm'] = err_norm
        info['nrefine'] = nrefine

        # coll_verts = model.get_collision_verts()

        if abs_tol is not None:
            # step control method that prevents crossing the midline in one step near collision
            # TODO: I think i deleted this so you'll have to got to and old commit to find it....
            refine, dt = refine_initial_collision(model, uva0, uva1, dt)

            # Step control method from [1]
            if err_norm > abs_tol_bounds[1]*abs_tol or err_norm < abs_tol_bounds[0]*abs_tol:
                dt = (abs_tol/err_norm)**(1/3) * dt
                refine = True
        else:
            refine = False

    return uva1, qp1, dt, info

def newton_solve(u, du, jac, res, bcs, **kwargs):
    """
    Solves the system using a newton method.

    Parameters
    ----------
    u : dfn.cpp.la.Vector
        The initial guess of the solution.
    du : dfn.cpp.la.Vector
        A vector for storing increments in the solution.
    res : callable(dfn.GenericVector) -> dfn.cpp.la.Vector
    jac : callable(dfn.GenericVector) -> dfn.cpp.la.Matrix
    bcs : list of dfn.DirichletBC

    Returns
    -------
    u1 : dfn.Function
    """
    omega = kwargs.get('relaxation', 1.0)
    linear_solver = kwargs.get('linear_solver', 'petsc')
    abs_tol = kwargs.get('abs_tol', 1e-8)
    rel_tol = kwargs.get('rel_tol', 1e-6)
    maxiter = kwargs.get('maxiter', 25)

    abs_err = 1.0
    rel_err = 1.0

    _res = res(u)
    for bc in bcs:
        bc.apply(_res)
    res_norm0 = _res.norm('l2')
    res_norm1 = 1.0

    ii = 0
    while abs_err > abs_tol and rel_err > rel_tol and ii < maxiter:
        _jac = jac(u)
        for bc in bcs:
            bc.apply(_jac, _res)

        dfn.solve(_jac, du, _res, linear_solver)

        u[:] = u - omega*du

        _res = res(u)
        for bc in bcs:
            bc.apply(_res)
        res_norm1 = _res.norm('l2')

        rel_err = abs((res_norm1 - res_norm0)/res_norm0)
        abs_err = res_norm1

        ii += 1

    info = {'niter': ii, 'abs_err': abs_err, 'rel_err': rel_err}
    return u, info

def newmark_error_estimate(a1, a0, dt, beta=1/4):
    """
    Return an estimate of the truncation error in `u` over the step.

    Error is esimated using eq (18) in [1]. Note that their paper defines $\beta2$ as twice $\beta$
    in the original newmark notation (used here). Therefore the beta term is multiplied by 2.

    [1] A simple error estimator and adaptive time stepping procedure for dynamic analysis.
    O. C. Zienkiewicz and Y. M. Xie. Earthquake Engineering and Structural Dynamics, 20:871-887
    (1991).

    Parameters
    ----------
    a1 : dfn.Vector()
        The newmark prediction of acceleration at :math:`n+1`
    a0 : dfn.Vector()
        The newmark prediction of acceleration at :math:`n`
    dt : float
        The time step integrated over
    beta : float
        The newmark-beta method :math:`beta` parameter

    Returns
    -------
    dfn.Vector()
        An estimate of the error in :math:`u_{n+1}`
    """
    return 0.5*dt**2*(2*beta - 1/3)*(a1-a0)
