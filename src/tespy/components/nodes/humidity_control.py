# -*- coding: utf-8

"""Module of class HumidityControl.


This file is part of project TESPy (github.com/oemof/tespy). It's copyrighted
by the contributors recorded in the version control history of the file,
available from its original location tespy/components/nodes/humidity_control.py

SPDX-License-Identifier: MIT
"""

from venv import logger
from tespy.components.component import component_registry
from tespy.components.nodes.base import NodeBase
from tespy.tools.data_containers import ComponentMandatoryConstraints as dc_cmc
from tespy.tools.data_containers import SimpleDataContainer as dc_simple
from tespy.tools.fluid_properties import dT_mix_dph
from tespy.tools.fluid_properties import dT_mix_pdh
from tespy.tools.fluid_properties.mixtures import w_mix_fluid_data

# from tespy.tools.fluid_properties import dT_mix_ph_dfluid


@component_registry
class HumidityControl(NodeBase):
    r"""
    A humidity control handles the water content from a humid air flow.
    
    **Mandatory Equations**

    - :py:meth:`tespy.components.nodes.base.NodeBase.mass_flow_func`
    - :py:meth:`tespy.components.nodes.base.NodeBase.pressure_structure_matrix`
    - :py:meth:`tespy.components.nodes.humidity_control.HumidityControl.fluid_func`
    - :py:meth:`tespy.components.nodes.humidity_control.HumidityControl.energy_balance_func`

    Inlets/Outlets

    - in1: inlet with humid air
    - in2: inlet of liquid water or ice
    - out1: outlet with humid air
    - out2: outlet of liquid water or ice 

    Note
    ----
    Fluid separation does not affect the energy balance since all properties
    are calculated with respect to the dry air mass flow. However, if water is
    added to the *unsaturated* humid air flow, the outlet enthalpy of the humid
    air flow will be higher than the inlet enthalpy.

    Parameters
    ----------
    label : str
        The label of the component.

    design : list
        List containing design parameters (stated as String).

    offdesign : list
        List containing offdesign parameters (stated as String).

    design_path : str
        Path to the components design case.

    local_offdesign : boolean
        Treat this component in offdesign mode in a design calculation.

    local_design : boolean
        Treat this component in design mode in an offdesign calculation.

    char_warnings : boolean
        Ignore warnings on default characteristics usage for this component.

    printout : boolean
        Include this component in the network's results printout.

    h2o_in : boolean
        Set to ``True`` if water is added to the humid air flow.

    h2o_out : boolean
        Set to ``True`` if water is removed from the humid air flow.

    Example
    -------
    The separator is used to split up a single mass flow into a specified
    number of different parts at identical pressure and temperature but
    different fluid composition. Fluids can be separated from each other.

    >>> from tespy.components import Sink, Source, Separator
    >>> from tespy.connections import Connection
    >>> from tespy.networks import Network
    >>> nw = Network(iterinfo=False)
    >>> nw.units.set_defaults(**{
    ...     "pressure": "bar", "temperature": "degC"
    ... })
    >>> so = Source('source')
    >>> si1 = Sink('sink1')
    >>> si2 = Sink('sink2')
    >>> s = Separator('separator', num_out=2)
    >>> inc = Connection(so, 'out1', s, 'in1')
    >>> outg1 = Connection(s, 'out1', si1, 'in1')
    >>> outg2 = Connection(s, 'out2', si2, 'in1')
    >>> nw.add_conns(inc, outg1, outg2)

    An Air (simplified) mass flow of 5 kg/s is split up into two mass flows.
    One mass flow of 1 kg/s containing 10 % oxygen and 90 % nitrogen leaves the
    separator. It is possible to calculate the fluid composition of the second
    mass flow. Specify starting values for the second mass flow fluid
    composition for calculation stability.

    >>> inc.set_attr(fluid={'O2': 0.23, 'N2': 0.77}, p=1, T=20, m=5)
    >>> outg1.set_attr(fluid={'O2': 0.1, 'N2': 0.9}, m=1)
    >>> outg2.set_attr(fluid0={'O2': 0.5, 'N2': 0.5})
    >>> nw.solve('design')
    >>> outg2.fluid.val['O2']
    0.2625

    In the same way, it is possible to specify one of the fluid components in
    the second mass flow instead of the first mass flow. The solver will find
    the mass flows matching the desired composition. 65 % of the mass flow
    will leave the separator at the second outlet the case of 30 % oxygen
    mass fraction for this outlet.

    >>> outg1.set_attr(m=None)
    >>> outg2.set_attr(fluid={'O2': 0.3})
    >>> nw.solve('design')
    >>> outg2.fluid.val['O2']
    0.3
    >>> round(outg2.m.val_SI / inc.m.val_SI, 2)
    0.65
    """

    def __init__(self, label, **kwargs):
        # We cannot add water for now, this needs a different way of
        # propagating the fluid wrapper.
        if "h2o_in" in kwargs and kwargs["h2o_in"]:
            msg = "Adding water to the humid air flow is currently not supported."
            raise NotImplementedError(msg)
        super().__init__(label, **kwargs)

    def set_attr(self, **kwargs):
        # We cannot add water for now, this needs a different way of
        # propagating the fluid wrapper.
        if "h2o_in" in kwargs and kwargs["h2o_in"]:
            msg = "Adding water to the humid air flow is currently not supported."
            raise NotImplementedError(msg)
        super().set_attr(**kwargs)

    def get_parameters(self):
        params = NodeBase.get_parameters(self)
        params.update({
            'h2o_in': dc_simple(
                val=False,
                description="set to True if water is added to the humid air flow"
            ),
            'h2o_out': dc_simple(
                val=False,
                description="set to True if water is removed from the humid air flow"
            )
        })
        return params
    
    def _update_num_eq(self):
        self.variable_fluids = set(
            [fluid for c in self.inl + self.outl for fluid in c.fluid.is_var]
        )
        num_fluid_eq = len(self.variable_fluids)
        if num_fluid_eq == 0:
            num_fluid_eq = 1
            self.variable_fluids = [list(self.inl[0].fluid.is_set)[0]]

        self.constraints["fluid_constraints"].num_eq = num_fluid_eq

    def get_mandatory_constraints(self):
        # cmc = super().get_mandatory_constraints()
        cmc = {}
        # overwrite the mass flow balance constraint of the base class 
        # with a dry air mass flow balance constraint
        cmc.update({
            'dry_air_mass_flow_constraints': dc_cmc(**{
                'num_eq_sets': 1,
                'func': self.dry_air_mass_flow_func,
                'dependents': self.dry_air_mass_flow_dependents,
                'description': 'dry air mass balance constraint'
            })
        })
        # overwrite the generic fluid balance constraint of the base class
        # with a water balance constraint since dry air is handled by the
        # mass flow balance constraint already
        # cmc.update({
        #     'water_mass_flow_constraints': dc_cmc(**{
        #         'num_eq_sets': 1,
        #         'func': self.water_mass_flow_func,
        #         'dependents': self.water_mass_flow_dependents,
        #         'description': 'water mass balance constraints'
        #     })
        # })
        cmc.update({
            'fluid_constraints': dc_cmc(**{
                'num_eq_sets': self.num_o,
                'func': self.fluid_func,
                'deriv': self.fluid_deriv,
                'dependents': self.fluid_dependents,
                'description': 'fluid mass fraction balance constraints'
            })
        })
        cmc.update({
            'energy_balance_constraints': dc_cmc(**{
                'num_eq_sets': self.num_o,
                'func': self.energy_balance_func,
                'deriv': self.energy_balance_deriv,
                'dependents': self.energy_balance_dependents,
                'description': 'equal temperature at all outlets constraints'
            })
        })
        cmc.update({
            'pressure_constraints': dc_cmc(**{
                'num_eq_sets': self.num_o,
                'structure_matrix': self.pressure_structure_matrix,
                'description': 'pressure equality constraints'
            })
        })
        return cmc

    def inlets(self):
        return ['in1'] + (['in2'] if self.h2o_in.val else [])

    def outlets(self):
        return ['out1'] + (['out2'] if self.h2o_out.val else [])

    def propagate_wrapper_to_target(self, branch):
        branch["components"] += [self]
        for outconn in self.outl:
            branch["connections"] += [outconn]
            outconn.target.propagate_wrapper_to_target(branch)

    def dry_air_mass_flow_func(self):
        r"""
        Calculate the residual value for dry air mass flow balance equation.

        Returns
        -------
        res : float
            Residual value of equation.

            .. math::

                0 = \dot{m}_{in,1} - \dot{m}_{out,1}
        """
        res = 0.0
        res += self.inl[0].m.val_SI
        res -= self.outl[0].m.val_SI
        return res

    def dry_air_mass_flow_dependents(self):
        return [self.inl[0].m, self.outl[0].m]

    def water_mass_flow_func(self):
        r"""
        Calculate the vector of residual values for fluid balance equations.

        Returns
        -------
        residual : list
            Vector of residual values for component's fluid balance.

            .. math::

                0 = \dot{m}_{in,1} \cdot w_{in,1}
                  + \dot{mH2O}_{in,1}
                  + \dot{m}_{in,2}
                  - \dot {m}_{out,1} \cdot w_{out,1}
                  - \dot{mH2O}_{out,1}
                  - \dot{m}_{out,2}
        """
        residual = 0.0
        # residual += self.inl[0].m.val_SI * self.inl[0].w.val_SI
        # residual += self.inl[0].mH2O.val_SI
        w_mixture_in = w_mix_fluid_data(self.inl[0].fluid_data)
        residual += self.inl[0].m.val_SI * w_mixture_in
        if self.h2o_in.val:
            residual += self.inl[1].m.val_SI
        # residual -= self.outl[0].m.val_SI * self.outl[0].w.val_SI
        # residual -= self.outl[0].mH2O.val_SI
        w_mixture_out = w_mix_fluid_data(self.outl[0].fluid_data)
        residual -= self.outl[0].m.val_SI * w_mixture_out
        if self.h2o_out.val:
            residual -= self.outl[1].m.val_SI
        return residual

    def water_mass_flow_dependents(self):
        m_dot_dry_air = self.dry_air_mass_flow_dependents()
        m_dot_water = []
        if self.h2o_in.val:
            m_dot_water += [self.inl[1].m]
        if self.h2o_out.val:
            m_dot_water += [self.outl[1].m]
        # variable_fluids = set(
        #     [fluid for c in self.inl + self.outl for fluid in c.fluid.is_var]
        # )
        return m_dot_dry_air + m_dot_water
    
    def fluid_func(self):
        residual = []
        for fluid in self.variable_fluids:
            res = 0.0
            for i in self.inl:
                res += i.fluid.val[fluid] * i.m.val_SI
            for o in self.outl:
                res -= o.fluid.val[fluid] * o.m.val_SI
            residual += [res]
        return residual

    def fluid_deriv(self, increment_filter, k, dependents=None):
        r"""
        Calculate partial derivatives of fluid balance.

        Parameters
        ----------
        increment_filter : ndarray
            Matrix for filtering non-changing variables.

        k : int
            Position of derivatives in Jacobian matrix (k-th equation).
        """
        for fluid in self.variable_fluids:
            for i in self.inl:
                self._partial_derivative(i.m, k, i.fluid.val[fluid], increment_filter)
                if fluid in i.fluid.is_var:
                    self.jacobian[k, i.fluid.J_col[fluid]] = i.m.val_SI
            for o in self.outl:
                self._partial_derivative(o.m, k, -o.fluid.val[fluid], increment_filter)
                if fluid in o.fluid.is_var:
                    self.jacobian[k, o.fluid.J_col[fluid]] = -o.m.val_SI
            k += 1

    def fluid_dependents(self):
        return {
            "scalars": [
                [c.m for c in self.inl + self.outl]
                for f in self.variable_fluids
            ],
            "vectors": [{
                c.fluid: set(f) & c.fluid.is_var for c in self.inl + self.outl
            } for f in self.variable_fluids]
        }

    def energy_balance_func(self):
        r"""
        Calculate energy balance.

        Returns
        -------
        residual : list
            Residual value of energy balance.

            .. math::

                0 = T_{in} - T_{out,j}\\
                \forall j \in \text{outlets}
        """
        residual = []
        T_in = self.inl[0].calc_T()
        for o in self.outl:
            residual += [T_in - o.calc_T()]
        return residual

    def energy_balance_deriv(self, increment_filter, k, dependents=None):
        r"""
        Calculate partial derivatives of energy balance.

        Parameters
        ----------
        increment_filter : ndarray
            Matrix for filtering non-changing variables.

        k : int
            Position of derivatives in Jacobian matrix (k-th equation).
        """
        i = self.inl[0]
        dT_dp_in = 0
        dT_dh_in = 0
        if i.p.is_var:
            # outlet pressure must be variable as well in this case!
            dT_dp_in = dT_mix_dph(i.p.val_SI, i.h.val_SI, i.fluid_data, i.mixing_rule)
        if i.h.is_var:
            dT_dh_in = dT_mix_pdh(i.p.val_SI, i.h.val_SI, i.fluid_data, i.mixing_rule)

        for o in self.outl:
            args = (o.p.val_SI, o.h.val_SI, o.fluid_data, o.mixing_rule)

            dT_dp_out = 0
            if o.p.is_var:
                dT_dp_out = -dT_mix_dph(*args)
            # pressure is always coupled
            self._partial_derivative(i.p, k, dT_dp_in - dT_dp_out)

            dT_dh_out = 0
            if o.h.is_var:
                dT_dh_out = -dT_mix_pdh(*args)

            # enthalpy is not necessarily coupled
            if i.h._reference_container == o.h._reference_container:
                self._partial_derivative(i.h, k, dT_dh_in - dT_dh_out)
            else:
                self._partial_derivative(i.h, k, dT_dh_in)
                self._partial_derivative(o.h, k, dT_dh_out)

            k += 1

    def energy_balance_dependents(self):
        res = []
        for o in self.outl:
            res_o = [o.p, o.h]
            for i in self.inl:
                res_o += [i.p, i.h]
            res.append(res_o)
        return res


if __name__ == "__main__":
    from tespy.components import Sink, Source, Separator
    from tespy.connections import HAConnection, Connection
    from tespy.networks import Network
    nw = Network()
    nw.units.set_defaults(**{
        "pressure": "bar", "temperature": "degC"
    })
    so = Source('source')
    si1 = Sink('sink1')
    si2 = Sink('sink2')
    # s = Separator('separator', num_out=2)
    s = HumidityControl('separator', h2o_in=False, h2o_out=True)
    air_in = HAConnection(so, 'out1', s, 'in1')
    air_out = HAConnection(s, 'out1', si1, 'in1')
    h2o_out = Connection(s, 'out2', si2, 'in1')
    nw.add_conns(air_in, air_out, h2o_out)
    air_in.set_attr(p=1, T=20, m=5)
    air_in.set_attr(fluid={'air': 0.99, 'water': 0.01})
    air_out.set_attr(fluid={'air': 0.995, 'water': 0.005})
    # air_out.set_attr(m=4)
    # air_out.set_attr(T=20)
    h2o_out.set_attr(fluid={'air': 0.00, 'water': 1.0})

    nw.solve('design')
    print(air_out.fluid.val)