This project implements a collection of vocal fold (VF) finite element (FE) models and 1D fluid
models that can be coupled together to simulated VF flow induced self-oscillation.

Todo
--------
- [] Refactor logging. I'm pretty sure the way logging is currently used is not proper and will lead
     to weird behaviour.

- [] Implement a block vector to store tuples of states, for example, (u, v, a) or (q, p)
- [] Speed up block matrix formation/matrix permutation methods
- [x] Implement a newton method for solving the fully coupled FSI problem

- [] Refactor the class definitions for functionals. I have a feeling many definitions included in the
  functional are not needed.
- [] Implement functionality to allow functional objects to be added/multiplied/etc. together. This is
  commonly used, for example, in forming penalty functional when one functional is the objective
  and another functional acts as a penalty.

- [] Create a generic parameterization that includes all variable parameters. Other parameterizations
     can then be derived from this generic one by removing known parameters, or specifying constant
     values.

- [] Add post-processing functionality to quickly evaluate optimization results
- [] Formalize/refactor how optimization progress is saved
- [x] Refactor hard coded callback functions out of objective function object
- [] Fix bug where exceptions are 'hidden' somehow in the optimization loop; this occurs when an
     exception such as accessing missing keys just gets ignored and doesn't cause the optimization
     code to throw an error and stop. This one is very confusing.
