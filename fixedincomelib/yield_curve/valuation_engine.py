"""Analytic cashflow, stream and composite-product valuation on the IFR model."""

import numpy as np

from fixedincomelib.model import ModelType
from fixedincomelib.product import ProductFixedAccruedCashflow
from fixedincomelib.valuation import (
    AnalyticValParam, FundingIndexParameter, ValuationEngineProduct,
    ValuationEngineProductRegistry,
)


# Stream and composite engines follow the instructor template's decomposition.
from fixedincomelib.date import TermOrDate
from fixedincomelib.product import (
    ProductForwardRateCashflow, ProductOvernightIndexCashflow, ProductInterestRateStream,
    ProductFRA, ProductRFRSwap, ProductOvernightIndexBasisSwap, PayOrReceive,
)
from fixedincomelib.valuation.report import CashflowsReport
from fixedincomelib.yield_curve.valuation_engine_analytics import (
    ValuationEngineAnalyticsForwardRate, ValuationEngineAnalyticsOvernightIndex,
)


class ValuationEngineProductFixedAccrued(ValuationEngineProduct):
    def __init__(self, model, valuation_parameters_collection, product, request):
        super().__init__(model, valuation_parameters_collection, product, request)
        funding_parameter = valuation_parameters_collection.get_vp_from_build_method_collection(
            FundingIndexParameter._vp_type,
        )
        self.funding_index_ = funding_parameter.get_funding_index(product.currency)

    def calculate_value(self) -> None:
        product = self.product_
        self.value_ = self.cash_ = 0.0
        if product.payment_date < self.value_date:
            return
        # Notional already carries the pay/receive sign; accrued is a fraction.
        amount = product.notional * product.accrued
        if product.payment_date == self.value_date:
            self.value_ = self.cash_ = amount
        else:
            self.value_ = amount * self.model.discount_factor(self.funding_index_, product.payment_date)

    def calculate_risk(
        self, gradient: list[np.ndarray], scaler: float = 1.0, accumulate: bool = False,
    ) -> None:
        product = self.product_
        if product.payment_date <= self.value_date:
            self.model.resize_gradient(gradient)
            if not accumulate:
                for block in gradient:
                    block.fill(0.0)
            return
        self.model.discount_factor_gradient_wrt_state(
            self.funding_index_, product.payment_date, gradient,
            scaler=scaler * product.notional * product.accrued,
            accumulate=accumulate,
        )


ValuationEngineProductRegistry().register(
    (ModelType.YIELD_CURVE.to_string(), ProductFixedAccruedCashflow._product_type, AnalyticValParam._vp_type),
    ValuationEngineProductFixedAccrued,
)


class ValuationEngineInterestRateStream(ValuationEngineProduct):
    """Value each coupon on its payment date, using index and funding curves."""

    def __init__(self, model, valuation_parameters_collection, product, request):
        super().__init__(model, valuation_parameters_collection, product, request)
        self.stream_ = product
        funding = valuation_parameters_collection.get_vp_from_build_method_collection(FundingIndexParameter._vp_type)
        self.funding_index_ = funding.get_funding_index(product.currency)
        self.index_engines_ = []
        for i in range(product.num_cashflows()):
            cf = product.cashflow(i)
            if isinstance(cf, ProductForwardRateCashflow):
                engine = ValuationEngineAnalyticsForwardRate(
                    model, valuation_parameters_collection, cf.projection_index,
                    cf.effective_date, cf.termination_date, cf.accrual_basis)
            elif isinstance(cf, ProductOvernightIndexCashflow):
                engine = ValuationEngineAnalyticsOvernightIndex(
                    model, valuation_parameters_collection, cf.on_index,
                    cf.effective_date, TermOrDate(cf.termination_date), cf.compounding_method)
            else:
                engine = None
            self.index_engines_.append(engine)

    @staticmethod
    def _accrual(cf):
        if isinstance(cf, ProductOvernightIndexCashflow):
            return cf.on_index.dayCounter().yearFraction(cf.effective_date, cf.termination_date)
        return cf.accrued

    def calculate_value(self):
        self.value_ = self.cash_ = 0.0
        n = self.stream_.num_cashflows()
        self.payoffs_ = [0.0] * n
        self.dfs_ = [0.0] * n
        self.rates_ = [None] * n
        self.accruals_ = [self._accrual(self.stream_.cashflow(i)) for i in range(n)]
        for i in range(n):
            cf = self.stream_.cashflow(i)
            if cf.payment_date < self.value_date:
                continue
            index_engine = self.index_engines_[i]
            if index_engine is None:
                rate = self.stream_.fixed_rate
            else:
                index_engine.calculate_value()
                rate = index_engine.value()
            spread = cf.spread if isinstance(cf, ProductOvernightIndexCashflow) else 0.0
            self.rates_[i] = rate
            self.payoffs_[i] = cf.notional * self.accruals_[i] * (rate + spread)
            df = 1.0 if cf.payment_date == self.value_date else self.model.discount_factor(self.funding_index_, cf.payment_date)
            self.dfs_[i] = df
            self.value_ += self.payoffs_[i] * df
            if cf.payment_date == self.value_date:
                self.cash_ += self.payoffs_[i]


    def create_cash_flows_report(self):
        self.calculate_value()
        rows = []
        for i in range(self.stream_.num_cashflows()):
            cf = self.stream_.cashflow(i)
            rows.append({
                "Leg": "Stream", "Currency": cf.currency.code(),
                "Accrual Start": cf.effective_date.ISO(), "Accrual End": cf.termination_date.ISO(),
                "Payment Date": cf.payment_date.ISO(), "Notional": cf.notional,
                "Accrual": self.accruals_[i], "Rate": self.rates_[i],
                "Spread": cf.spread if isinstance(cf, ProductOvernightIndexCashflow) else 0.0,
                "Cashflow": self.payoffs_[i], "Discount Factor": self.dfs_[i],
                "PV": self.payoffs_[i] * self.dfs_[i],
            })
        return CashflowsReport(rows)


def _combine_cashflow_reports(legs):
    rows = []
    for name, sign, engine in legs:
        for original in engine.create_cash_flows_report().content:
            row = dict(original, Leg=name)
            for key in ("Notional", "Cashflow", "PV"):
                row[key] *= sign
            rows.append(row)
    return CashflowsReport(rows)


class ValuationEngineProductRfrSwap(ValuationEngineProduct):
    """Fixed and overnight-floating leg valuation."""

    def __init__(self, model, valuation_parameters_collection, product, request):
        super().__init__(model, valuation_parameters_collection, product, request)
        self.fixed_leg_sign_ = -1.0 if product.pay_or_rec == PayOrReceive.PAY else 1.0
        self.floating_leg_sign_ = -self.fixed_leg_sign_
        self.fixed_leg_engine_ = ValuationEngineInterestRateStream(model, valuation_parameters_collection, product.fixed_leg, request)
        self.floating_leg_engine_ = ValuationEngineInterestRateStream(model, valuation_parameters_collection, product.floating_leg, request)

    def calculate_value(self):
        #TODO
        self.fixed_leg_engine_.calculate_value()
        self.floating_leg_engine_.calculate_value()

        self.value_ = (
            self.fixed_leg_sign_ * self.fixed_leg_engine_.value
            + self.floating_leg_sign_ * self.floating_leg_engine_.value
        )

        self.cash_ = (
            self.fixed_leg_sign_ * self.fixed_leg_engine_.cash
            + self.floating_leg_sign_ * self.floating_leg_engine_.cash
        )

    def create_cash_flows_report(self):
        return _combine_cashflow_reports([
            ("Fixed", self.fixed_leg_sign_, self.fixed_leg_engine_),
            ("Floating", self.floating_leg_sign_, self.floating_leg_engine_),
        ])


class ValuationEngineProductFra(ValuationEngineProduct):
    """End-paid FRA valued as a fixed leg minus a term-floating leg."""

    def __init__(self, model, valuation_parameters_collection, product, request):
        super().__init__(model, valuation_parameters_collection, product, request)
        self.fixed_leg_sign_ = -1.0 if product.pay_or_rec == PayOrReceive.PAY else 1.0
        self.floating_leg_sign_ = -self.fixed_leg_sign_
        self.fixed_leg_engine_ = ValuationEngineInterestRateStream(model, valuation_parameters_collection, product.fixed_leg, request)
        self.floating_leg_engine_ = ValuationEngineInterestRateStream(model, valuation_parameters_collection, product.floating_leg, request)

    def calculate_value(self):
        self.fixed_leg_engine_.calculate_value()
        self.floating_leg_engine_.calculate_value()
        self.value_ = (self.fixed_leg_sign_ * self.fixed_leg_engine_.value +
                       self.floating_leg_sign_ * self.floating_leg_engine_.value)
        self.cash_ = (self.fixed_leg_sign_ * self.fixed_leg_engine_.cash +
                      self.floating_leg_sign_ * self.floating_leg_engine_.cash)

    def create_cash_flows_report(self):
        return _combine_cashflow_reports([
            ("Fixed", self.fixed_leg_sign_, self.fixed_leg_engine_),
            ("Floating", self.floating_leg_sign_, self.floating_leg_engine_),
        ])


class ValuationEngineProductOvernightIndexBasisSwap(ValuationEngineProduct):
    """Template decomposition: leg-1 index, leg-1 spread, and leg-2 index."""

    def __init__(self, model, valuation_parameters_collection, product, request):
        super().__init__(model, valuation_parameters_collection, product, request)
        self.floating_leg_1_sign_ = -1.0 if product.pay_or_rec == PayOrReceive.PAY else 1.0
        self.floating_leg_2_sign_ = -self.floating_leg_1_sign_
        self.floating_leg_1_basis_engine_ = ValuationEngineInterestRateStream(
            model, valuation_parameters_collection, product.floating_leg_1_basis, request)
        self.floating_leg_1_wo_basis_engine_ = ValuationEngineInterestRateStream(
            model, valuation_parameters_collection, product.floating_leg_1_wo_basis, request)
        self.floating_leg_2_engine_ = ValuationEngineInterestRateStream(
            model, valuation_parameters_collection, product.floating_leg_2, request)

    def _legs(self):
        return [("Leg 1 index", self.floating_leg_1_sign_, self.floating_leg_1_wo_basis_engine_),
                ("Leg 1 spread", self.floating_leg_1_sign_, self.floating_leg_1_basis_engine_),
                ("Leg 2 index", self.floating_leg_2_sign_, self.floating_leg_2_engine_)]

    def calculate_value(self):
        #TODO
        self.value_ = 0.0
        self.cash_ = 0.0

        for name, sign, engine in self._legs():
            engine.calculate_value()
            self.value_ += sign * engine.value
            self.cash_ += sign * engine.cash

    def create_cash_flows_report(self):
        return _combine_cashflow_reports(self._legs())


for _product, _engine in (
    (ProductInterestRateStream, ValuationEngineInterestRateStream),
    (ProductFRA, ValuationEngineProductFra),
    (ProductRFRSwap, ValuationEngineProductRfrSwap),
    (ProductOvernightIndexBasisSwap, ValuationEngineProductOvernightIndexBasisSwap),
):
    ValuationEngineProductRegistry().register(
        (ModelType.YIELD_CURVE.to_string(), _product._product_type, AnalyticValParam._vp_type), _engine)
