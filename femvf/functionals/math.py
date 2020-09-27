"""
Implements some basic math operations tha can be used to combine functionals into new functionals.
"""
import numpy as np
from .abstract import AbstractFunctional
from .basic import Scalar

from ..parameters.properties import SolidProperties, FluidProperties


def add(funa, funb):
    """
    Add functionals
    """
    funa, funb = _convert_float(funa, funb)
    _validate(funa, funb)

    return Sum(funa.model, funa, funb)

def sub(funa, funb):
    """
    Add functionals
    """
    funa, funb = _convert_float(funa, funb)
    _validate(funa, funb)

    return Sum(funa.model, funa, mul(-1.0, funb))

def mul(funa, funb):
    funa, funb = _convert_float(funa, funb)
    _validate(funa, funb)

    return Product(funa.model, funa, funb)

def power(funa, funb):
    funa, funb = _convert_float(funa, funb)
    _validate(funa, funb)

    return Power(funa.model, funa, funb)

def _validate(*funs):
    _model = funs[0].model

    for fun in funs[1:]:
        if fun.model != _model:
            raise ValueError("Functionals must use the same model")

def _convert_float(funa, funb):
    """
    Converts floats to scalar functionals
    """
    funa_isfunc = isinstance(funa, AbstractFunctional)
    funb_isfunc = isinstance(funb, AbstractFunctional)

    if funa_isfunc and funb_isfunc:
        pass
    elif funa_isfunc and isinstance(funb, float):
        funb = Scalar(funa.model, funb)
    elif funb_isfunc and isinstance(funa, float):
        funa = Scalar(funb.model, funa)
    else:
        raise TypeError("something went wrong")

    return funa, funb


class Sum(AbstractFunctional):
    """
    A functional representing a + b, where a and b are functionals
    """
    def __init__(self, model, funa, funb):
        super().__init__(model, funa, funb)

    def eval(self, f):
        funa, funb = self.funcs
        return funa(f) + funb(f)

    @staticmethod
    def _sum_drule(funa, funb, dname, *args):
        dfuna = getattr(funa, dname)
        dfunb = getattr(funb, dname)

        # a, b = funa(*args), funb(*args)
        da, db = dfuna(*args), dfunb(*args)
        if isinstance(da, (SolidProperties, FluidProperties)) and isinstance(db, (SolidProperties, FluidProperties)):
            out = da.copy()
            out.vector[:] = da.vector + db.vector
            return out
        else:
            return da + db

    def eval_duva(self, f, n):
        return self._sum_drule(*self.funcs, 'duva', f, n)

    def eval_dqp(self, f, n):
        return self._sum_drule(*self.funcs, 'dqp', f, n)

    def eval_dsolid(self, f):
        return self._sum_drule(*self.funcs, 'dsolid', f)

    def eval_dfluid(self, f):
        return self._sum_drule(*self.funcs, 'dfluid', f)

    def eval_ddt(self, f, n):
        return self._sum_drule(*self.funcs, 'ddt', f, n)

    def eval_dt0(self, f, n):
        return self._sum_drule(*self.funcs, 'dt0', f, n)

class Product(AbstractFunctional):
    """
    A functional representing a * b, where a and b are functionals
    """
    def __init__(self, model, funa, funb):
        super().__init__(model, funa, funb)

    def eval(self, f):
        funa, funb = self.funcs
        return funa(f) * funb(f)

    @staticmethod
    def _product_drule(funa, funb, dname, *args):
        dfuna = getattr(funa, dname)
        dfunb = getattr(funb, dname)

        a, b = funa(args[0]), funb(args[0])
        da, db = dfuna(*args), dfunb(*args)

        if isinstance(da, (SolidProperties, FluidProperties)) and isinstance(db, (SolidProperties, FluidProperties)):
            out = da.copy()
            out.vector[:] = da.vector*b + a*db.vector
            return out
        else:
            return da*b + a*db

    def eval_duva(self, f, n):
        return self._product_drule(*self.funcs, 'duva', f, n)

    def eval_dqp(self, f, n):
        return self._product_drule(*self.funcs, 'dqp', f, n)

    def eval_dsolid(self, f):
        return self._product_drule(*self.funcs, 'dsolid', f)

    def eval_dfluid(self, f):
        return self._product_drule(*self.funcs, 'dfluid', f)

    def eval_ddt(self, f, n):
        return self._product_drule(*self.funcs, 'ddt', f, n)

    def eval_dt0(self, f, n):
        return self._product_drule(*self.funcs, 'dt0', f, n)

class Power(AbstractFunctional):
    """
    A functional representing a ** b, where a and b are functionals
    """
    def eval(self, f):
        funa, funb = self.funcs
        return funa(f) ** funb(f)

    @staticmethod
    def _power_drule(funa, funb, dname, *args):
        dfuna = getattr(funa, dname)
        dfunb = getattr(funb, dname)

        a, b = funa(args[0]), funb(args[0])
        da, db = dfuna(*args), dfunb(*args)

        if isinstance(da, (SolidProperties, FluidProperties)) and isinstance(db, (SolidProperties, FluidProperties)):
            out = da.copy()
            out.vector[:] = b*a**(b-1)*da.vector + np.log(a)*a**b*db.vector
            return out
        else:
            return b*a**(b-1)*da + np.log(a)*a**b*db

    def eval_duva(self, f, n):
        return self._power_drule(*self.funcs, 'duva', f, n)

    def eval_dqp(self, f, n):
        return self._power_drule(*self.funcs, 'dqp', f, n)

    def eval_dsolid(self, f):
        return self._power_drule(*self.funcs, 'dsolid', f)

    def eval_dfluid(self, f):
        return self._power_drule(*self.funcs, 'dfluid', f)

    def eval_ddt(self, f, n):
        return self._power_drule(*self.funcs, 'ddt', f, n)

    def eval_dt0(self, f, n):
        return self._power_drule(*self.funcs, 'dt0', f, n)
