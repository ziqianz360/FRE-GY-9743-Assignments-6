"""Cashflow building blocks and the instructor template's interest-rate products."""

from typing import Optional

import QuantLib as ql

from fixedincomelib.date.basics import Date, Period, TermOrDate
from fixedincomelib.date.utilities import accrued, add_period, make_schedule, move_to_business_day
from fixedincomelib.market.basics import (
    AccrualBasis, BusinessDayConvention, Currency, HolidayConvention,
)
from fixedincomelib.market.data_conventions import CompoundingMethod
from fixedincomelib.market.registries import IndexRegistry
from fixedincomelib.product.product_interfaces import Product, ProductVisitor
from fixedincomelib.product.utilities import LongOrShort, PayOrReceive
from fixedincomelib.product.product_portfolio import ProductPortfolio
from fixedincomelib.product.product_interfaces import ProductBuilderRegistry

__all__ = [
    "ProductCashflow", "ProductFixedAccruedCashflow", "ProductOvernightIndexCashflow",
]


class ProductCashflow(Product):
    """Abstract cashflow with currency, signed notional and payment date."""

    def __init__(self, currency: Currency, notional: float, payment_date: Date) -> None:
        super().__init__()
        self.currency_ = currency
        self.notional_ = notional
        self.long_or_short_ = LongOrShort.LONG if notional >= 0 else LongOrShort.SHORT
        self.payment_date_ = Date(payment_date)
        self.last_date_ = self.payment_date_

    @property
    def payment_date(self) -> Date:
        return self.payment_date_


class ProductFixedAccruedCashflow(ProductCashflow):
    """Fixed-accrual cashflow; accrued is a year fraction, not a cash amount."""

    _version = 1
    _product_type = "PRODUCT_FIXED_ACCRUED"

    def __init__(
        self,
        effective_date: Date,
        termination_date: Date,
        currency: Currency,
        notional: float,
        accrual_basis: AccrualBasis,
        payment_date: Optional[Date] = None,
        business_day_convention: Optional[BusinessDayConvention] = None,
        holiday_convention: Optional[HolidayConvention] = None,
    ) -> None:
        effective_date = Date(effective_date)
        termination_date = Date(termination_date)
        super().__init__(
            currency, notional, termination_date if payment_date is None else payment_date,
        )
        self.effective_date_ = self.first_date_ = effective_date
        self.termination_date_ = termination_date
        self.accrual_basis_ = accrual_basis
        self.business_day_convention_ = (
            BusinessDayConvention("F") if business_day_convention is None else business_day_convention
        )
        self.holiday_convention_ = (
            HolidayConvention("USGS") if holiday_convention is None else holiday_convention
        )
        self.accrued_ = accrued(
            self.effective_date_, self.termination_date_, self.accrual_basis_,
            self.business_day_convention_, self.holiday_convention_,
        )

    @property
    def effective_date(self) -> Date:
        return self.effective_date_

    @property
    def termination_date(self) -> Date:
        return self.termination_date_

    @property
    def accrual_basis(self) -> AccrualBasis:
        return self.accrual_basis_

    @property
    def business_day_convention(self) -> BusinessDayConvention:
        return self.business_day_convention_

    @property
    def holiday_convention(self) -> HolidayConvention:
        return self.holiday_convention_

    @property
    def accrued(self) -> float:
        return self.accrued_

    def accept(self, visitor: ProductVisitor):
        return visitor.visit(self)

    def serialize(self) -> dict:
        return {
            "VERSION": self._version,
            "TYPE": self._product_type,
            "EFFECTIVE_DATE": self.effective_date.ISO(),
            "TERMINATION_DATE": self.termination_date.ISO(),
            "PAYMENT_DATE": self.payment_date.ISO(),
            "ACCRUAL_BASIS": self.accrual_basis.value_str,
            "BUSINESS_DAY_CONVENTION": self.business_day_convention.value_str,
            "HOLIDAY_CONVENTION": self.holiday_convention.value_str,
            "NOTIONAL": self.notional,
            "CURRENCY": self.currency.value_str,
        }

    @classmethod
    def deserialize(cls, input_dict: dict) -> "ProductFixedAccruedCashflow":
        return cls(
            Date(input_dict["EFFECTIVE_DATE"]), Date(input_dict["TERMINATION_DATE"]),
            Currency(input_dict["CURRENCY"]), float(input_dict["NOTIONAL"]),
            AccrualBasis(input_dict["ACCRUAL_BASIS"]), Date(input_dict["PAYMENT_DATE"]),
            BusinessDayConvention(input_dict["BUSINESS_DAY_CONVENTION"]),
            HolidayConvention(input_dict["HOLIDAY_CONVENTION"]),
        )


class ProductOvernightIndexCashflow(ProductCashflow):
    """Overnight-index cashflow terms, with spread as an annual decimal rate."""

    _version = 1
    _product_type = "PRODUCT_OVERNIGHT_INDEX_CASHFLOW"

    def __init__(
        self,
        effective_date: Date,
        term_or_termination_date: TermOrDate,
        on_index: str,
        compounding_method: CompoundingMethod,
        spread: float,
        notional: float,
        payment_date: Optional[Date] = None,
    ) -> None:
        effective_date = Date(effective_date)
        on_index_obj = IndexRegistry().get(on_index)
        termination_date = term_or_termination_date.get_date()
        if term_or_termination_date.is_term():
            term = term_or_termination_date.get_term()
            termination_date = Date(on_index_obj.fixingCalendar().advance(
                effective_date, term, on_index_obj.businessDayConvention(),
            ))
        termination_date = Date(termination_date)
        super().__init__(
            Currency(on_index_obj.currency().code()), notional,
            termination_date if payment_date is None else payment_date,
        )
        self.on_index_str_ = on_index
        self.on_index_ = on_index_obj
        self.effective_date_ = self.first_date_ = effective_date
        self.termination_date_ = termination_date
        self.compounding_method_ = compounding_method
        self.spread_ = spread

    @property
    def on_index(self) -> ql.OvernightIndex:
        return self.on_index_

    @property
    def compounding_method(self) -> CompoundingMethod:
        return self.compounding_method_

    @property
    def effective_date(self) -> Date:
        return self.effective_date_

    @property
    def termination_date(self) -> Date:
        return self.termination_date_

    @property
    def spread(self) -> float:
        return self.spread_

    def accept(self, visitor: ProductVisitor):
        return visitor.visit(self)

    def serialize(self) -> dict:
        return {
            "VERSION": self._version,
            "TYPE": self._product_type,
            "EFFECTIVE_DATE": self.effective_date.ISO(),
            "TERMINATION_DATE": self.termination_date.ISO(),
            "PAYMENT_DATE": self.payment_date.ISO(),
            "ON_INDEX": self.on_index_str_,
            "SPREAD": self.spread,
            "COMPOUNDING_METHOD": self.compounding_method.to_string().upper(),
            "NOTIONAL": self.notional,
        }

    @classmethod
    def deserialize(cls, input_dict: dict) -> "ProductOvernightIndexCashflow":
        return cls(
            Date(input_dict["EFFECTIVE_DATE"]), TermOrDate(input_dict["TERMINATION_DATE"]),
            input_dict["ON_INDEX"], CompoundingMethod.from_string(input_dict["COMPOUNDING_METHOD"]),
            float(input_dict["SPREAD"]), float(input_dict["NOTIONAL"]),
            Date(input_dict["PAYMENT_DATE"]),
        )


class ProductForwardRateCashflow(ProductFixedAccruedCashflow):
    """A simple term-rate coupon: fixing at Ts, payment at Te by default.

    The projection index selects a curve. A term fixing is keyed by index,
    start, end and day count; it is distinct from a daily overnight fixing.
    """

    _product_type = "PRODUCT_FORWARD_RATE_CASHFLOW"

    def __init__(self, effective_date, termination_date, projection_index, notional,
                 accrual_basis, payment_date=None):
        index = IndexRegistry().get(projection_index)
        super().__init__(effective_date, termination_date, Currency(index.currency().code()),
                         notional, accrual_basis, payment_date,
                         BusinessDayConvention("NONE"), HolidayConvention("NONE"))
        self.projection_index_str_ = projection_index.upper()
        self.projection_index_ = index

    @property
    def projection_index(self):
        return self.projection_index_

    @property
    def fixing_date(self):
        return self.effective_date

    def serialize(self):
        content = super().serialize()
        content["PROJECTION_INDEX"] = self.projection_index_str_
        return content

    @classmethod
    def deserialize(cls, content):
        return cls(Date(content["EFFECTIVE_DATE"]), Date(content["TERMINATION_DATE"]),
                   content["PROJECTION_INDEX"], content["NOTIONAL"],
                   AccrualBasis(content["ACCRUAL_BASIS"]), Date(content["PAYMENT_DATE"]))


class ProductInterestRateStream(ProductPortfolio):
    """Template interest-rate leg, extended with a term-rate branch for FRA.

    Exactly one of fixed_rate and float_index is supplied. A floating stream
    uses overnight coupons when is_on_index=True, term coupons otherwise.
    accrual_period=None creates one coupon, as required by the teaching FRA.
    """

    _version = 1
    _product_type = "PRODUCT_INTEREST_RATE_STREAM"

    def __init__(
        self, effective_date, termination_date, accrual_period, notional, currency,
        accrual_basis, business_day_convention, holiday_convention,
        float_index=None, fixed_rate=None, is_on_index=True,
        ois_compounding=CompoundingMethod.COMPOUND, ois_spread=0.0,
        fixing_in_arrear=True, payment_offset=None,
        payment_business_day_convention=None, payment_holiday_convention=None,
        rule="BACKWARD", end_of_month=False,
    ):
        effective_date, termination_date = Date(effective_date), Date(termination_date)
        payment_offset = Period("0D") if payment_offset is None else payment_offset
        pay_bdc = payment_business_day_convention or BusinessDayConvention("F")
        pay_holidays = payment_holiday_convention or holiday_convention
        rule_name = rule.upper()
        generation_rule = {"BACKWARD": ql.DateGeneration.Backward,
                           "FORWARD": ql.DateGeneration.Forward}[rule_name]
        self.float_index_ = float_index
        self.fixed_rate_ = fixed_rate
        self.is_on_index_ = is_on_index
        self.specification_ = {
            "EFFECTIVE_DATE": effective_date.ISO(), "TERMINATION_DATE": termination_date.ISO(),
            "ACCRUAL_PERIOD": None if accrual_period is None else str(accrual_period),
            "NOTIONAL": notional, "CURRENCY": currency.code(),
            "ACCRUAL_BASIS": accrual_basis.value_str,
            "BUSINESS_DAY_CONVENTION": business_day_convention.value_str,
            "HOLIDAY_CONVENTION": holiday_convention.value_str,
            "FLOAT_INDEX": float_index, "FIXED_RATE": fixed_rate, "IS_ON_INDEX": is_on_index,
            "OIS_COMPOUNDING": ois_compounding.to_string(), "OIS_SPREAD": ois_spread,
            "FIXING_IN_ARREAR": fixing_in_arrear, "PAYMENT_OFFSET": str(payment_offset),
            "PAYMENT_BUSINESS_DAY_CONVENTION": pay_bdc.value_str,
            "PAYMENT_HOLIDAY_CONVENTION": pay_holidays.value_str,
            "RULE": rule_name, "END_OF_MONTH": end_of_month,
        }
        if accrual_period is None:
            # Explicit dates are already resolved by the FRA constructor.
            payment_date = add_period(termination_date, payment_offset, pay_bdc, pay_holidays)
            schedule_rows = [(effective_date, termination_date, payment_date)]
        else:
            # Adapt the template call to the existing native QuantLib date API.
            schedule = make_schedule(
                effective_date, termination_date, accrual_period, holiday_convention.value,
                business_day_convention.value, accrual_basis.value, rule=generation_rule,
                end_of_month=end_of_month, fix_in_arrear=fixing_in_arrear,
                payment_offset=payment_offset, payment_business_day_convention=pay_bdc.value,
                payment_holiday_convention=pay_holidays.value, as_dataframe=True,
            )
            schedule_rows = [(Date(row.StartDate), Date(row.EndDate), Date(row.PaymentDate))
                             for row in schedule.itertuples()]
        products = []
        for start, end, pay in schedule_rows:
            if float_index is not None:
                if is_on_index:
                    cf = ProductOvernightIndexCashflow(start, TermOrDate(end), float_index,
                                                      ois_compounding, ois_spread, notional, pay)
                else:
                    cf = ProductForwardRateCashflow(start, end, float_index, notional, accrual_basis, pay)
            else:
                cf = ProductFixedAccruedCashflow(start, end, currency, notional, accrual_basis, pay,
                                                BusinessDayConvention("NONE"), holiday_convention)
            products.append(cf)
        super().__init__(products)
        # A leg's notional is the contractual notional, not the sum across coupons.
        self.notional_ = notional
        self.currency_ = currency
        self.long_or_short_ = LongOrShort.LONG if notional >= 0 else LongOrShort.SHORT
        self.effective_date_ = products[0].effective_date
        self.termination_date_ = products[-1].termination_date

    @property
    def effective_date(self):
        return self.effective_date_

    @property
    def termination_date(self):
        return self.termination_date_

    @property
    def float_index(self):
        return self.float_index_

    @property
    def fixed_rate(self):
        return self.fixed_rate_

    def cashflow(self, i):
        return self.element(i)

    def num_cashflows(self):
        return self.num_elements_

    def serialize(self):
        return {"VERSION": self._version, "TYPE": self._product_type, **self.specification_}

    @classmethod
    def deserialize(cls, content):
        c = content
        return cls(
            Date(c["EFFECTIVE_DATE"]), Date(c["TERMINATION_DATE"]),
            None if c["ACCRUAL_PERIOD"] is None else Period(c["ACCRUAL_PERIOD"]),
            c["NOTIONAL"], Currency(c["CURRENCY"]), AccrualBasis(c["ACCRUAL_BASIS"]),
            BusinessDayConvention(c["BUSINESS_DAY_CONVENTION"]), HolidayConvention(c["HOLIDAY_CONVENTION"]),
            c["FLOAT_INDEX"], c["FIXED_RATE"], c["IS_ON_INDEX"],
            CompoundingMethod.from_string(c["OIS_COMPOUNDING"]), c["OIS_SPREAD"],
            c["FIXING_IN_ARREAR"], Period(c["PAYMENT_OFFSET"]),
            BusinessDayConvention(c["PAYMENT_BUSINESS_DAY_CONVENTION"]),
            HolidayConvention(c["PAYMENT_HOLIDAY_CONVENTION"]), c["RULE"], c["END_OF_MONTH"],
        )


# Keep the instructor template's class name available to its swap constructors.
InterestRateStream = ProductInterestRateStream


class ProductFRA(Product):
    """Fix at Ts, pay at Te; receive means receive fixed and pay floating."""

    _version = 1
    _product_type = "PRODUCT_FRA"

    def __init__(self, effective_date, term_or_termination_date, projection_index,
                 fixed_rate, pay_or_rec, notional, accrual_basis,
                 business_day_convention=None, holiday_convention=None):
        super().__init__()
        bdc = business_day_convention or BusinessDayConvention("F")
        holidays = holiday_convention or HolidayConvention("USGS")
        start = move_to_business_day(Date(effective_date), bdc, holidays)
        term = term_or_termination_date
        end = (add_period(start, term.get_term(), bdc, holidays) if term.is_term()
               else move_to_business_day(Date(term.get_date()), bdc, holidays))
        self.first_date_ = self.effective_date_ = self.fixing_date_ = start
        self.last_date_ = self.termination_date_ = self.payment_date_ = end
        self.projection_index_str_ = projection_index.upper()
        self.projection_index_ = IndexRegistry().get(projection_index)
        self.currency_ = Currency(self.projection_index_.currency().code())
        self.notional_, self.fixed_rate_, self.pay_or_rec_ = notional, fixed_rate, pay_or_rec
        self.long_or_short_ = LongOrShort.LONG
        self.accrual_basis_ = accrual_basis
        self.accrued_ = accrual_basis.value.yearFraction(start, end)
        self.business_day_convention_, self.holiday_convention_ = bdc, holidays
        common = dict(effective_date=start, termination_date=end, accrual_period=None,
                      notional=notional, currency=self.currency_, accrual_basis=accrual_basis,
                      business_day_convention=BusinessDayConvention("NONE"), holiday_convention=holidays,
                      payment_business_day_convention=BusinessDayConvention("NONE"))
        self.fixed_leg_ = InterestRateStream(**common, fixed_rate=fixed_rate)
        self.floating_leg_ = InterestRateStream(**common, float_index=projection_index, is_on_index=False)

    @property
    def effective_date(self):
        return self.effective_date_

    @property
    def termination_date(self):
        return self.termination_date_

    @property
    def fixing_date(self):
        return self.fixing_date_

    @property
    def payment_date(self):
        return self.payment_date_

    @property
    def projection_index(self):
        return self.projection_index_

    @property
    def fixed_rate(self):
        return self.fixed_rate_

    @property
    def pay_or_rec(self):
        return self.pay_or_rec_

    @property
    def accrual_basis(self):
        return self.accrual_basis_

    @property
    def accrued(self):
        return self.accrued_

    @property
    def fixed_leg(self):
        return self.fixed_leg_

    @property
    def floating_leg(self):
        return self.floating_leg_


    def accept(self, visitor):
        return visitor.visit(self)

    def serialize(self):
        return {
            "VERSION": self._version, "TYPE": self._product_type,
            "EFFECTIVE_DATE": self.effective_date.ISO(), "TERMINATION_DATE": self.termination_date.ISO(),
            "PROJECTION_INDEX": self.projection_index_str_, "FIXED_RATE": self.fixed_rate,
            "PAY_OR_REC": self.pay_or_rec.to_string(), "NOTIONAL": self.notional,
            "ACCRUAL_BASIS": self.accrual_basis.value_str,
            "BUSINESS_DAY_CONVENTION": self.business_day_convention_.value_str,
            "HOLIDAY_CONVENTION": self.holiday_convention_.value_str,
        }

    @classmethod
    def deserialize(cls, c):
        return cls(Date(c["EFFECTIVE_DATE"]), TermOrDate(c["TERMINATION_DATE"]),
                   c["PROJECTION_INDEX"], c["FIXED_RATE"], PayOrReceive.from_string(c["PAY_OR_REC"]),
                   c["NOTIONAL"], AccrualBasis(c["ACCRUAL_BASIS"]),
                   BusinessDayConvention(c["BUSINESS_DAY_CONVENTION"]), HolidayConvention(c["HOLIDAY_CONVENTION"]))


# Adapted from the instructor template.
class ProductRFRSwap(Product):

    _version = 1
    _product_type = "PRODUCT_RFR_SWAP"

    def __init__(
        self,
        effective_date: Date,
        term_or_termination_date: TermOrDate,
        payment_off_set: Period,
        on_index: str,
        fixed_rate: float,
        pay_or_rec: PayOrReceive,
        notional: float,
        accrual_period: Period,
        accrual_basis: AccrualBasis,
        floating_leg_accrual_period: Optional[Period] = None,
        pay_business_day_convention: Optional[BusinessDayConvention] = BusinessDayConvention("F"),
        pay_holiday_convention: Optional[HolidayConvention] = HolidayConvention("USGS"),
        spread: Optional[float] = 0.0,
        compounding_method: Optional[CompoundingMethod] = CompoundingMethod.COMPOUND,
    ) -> None:

        super().__init__()
        effective_date = move_to_business_day(Date(effective_date), pay_business_day_convention, pay_holiday_convention)

        self.on_index_str_ = on_index
        self.on_index_: ql.QuantLib.OvernightIndex = IndexRegistry().get(self.on_index_str_)
        self.pay_business_day_convention_ = pay_business_day_convention
        self.pay_holiday_convention_ = pay_holiday_convention
        self.first_date_ = self.effective_date_ = effective_date
        self.term_or_termination_date_ = term_or_termination_date
        self.termination_date_ = self.term_or_termination_date_.get_date()
        if self.term_or_termination_date_.is_term():
            calendar = self.on_index_.fixingCalendar()
            self.termination_date_ = Date(
                calendar.advance(
                    self.effective_date_,
                    self.term_or_termination_date_.get_term(),
                    self.on_index_.businessDayConvention(),
                )
            )
        # other attributes
        self.currency_ = Currency(self.on_index_.currency().code())
        self.fixed_rate_ = fixed_rate
        self.notional_ = notional
        self.spread_ = spread
        self.pay_or_rec_ = pay_or_rec
        self.long_or_short_ = LongOrShort.LONG if notional >= 0 else LongOrShort.SHORT
        self.pay_offset_ = payment_off_set
        self.accrual_basis_ = accrual_basis
        self.accrual_period_ = accrual_period
        self.floating_leg_accrual_period_ = (
            self.accrual_period_
            if floating_leg_accrual_period is None
            else floating_leg_accrual_period
        )
        self.compounding_method_ = compounding_method

        #TODO
        common = dict(
            effective_date=self.effective_date_,
            termination_date=self.termination_date_,
            notional=self.notional_,
            currency=self.currency_,
            accrual_basis=self.accrual_basis_,
            business_day_convention=self.pay_business_day_convention_,
            holiday_convention=self.pay_holiday_convention_,
            payment_offset=self.pay_offset_,
            payment_business_day_convention=self.pay_business_day_convention_,
            payment_holiday_convention=self.pay_holiday_convention_,
        )

        self.fixed_leg_ = InterestRateStream(
            **common,
            accrual_period=self.accrual_period_,
            fixed_rate=self.fixed_rate_,
        )

        self.floating_leg_ = InterestRateStream(
            **common,
            accrual_period=self.floating_leg_accrual_period_,
            float_index=self.on_index_str_,
            is_on_index=True,
            ois_compounding=self.compounding_method_,
            ois_spread=self.spread_,
        )

        last_dt_fixed = self.fixed_leg_.last_date
        last_dt_floating = self.floating_leg_.last_date
        self.last_date_ = last_dt_fixed if last_dt_fixed >= last_dt_floating else last_dt_floating

    def floating_leg_cash_flow(self, i: int) -> Product:
        return self.floating_leg_.element(i)

    def fixed_leg_cash_flow(self, i: int) -> Product:
        return self.fixed_leg_.element(i)

    @property
    def effective_date(self) -> Date:
        return self.effective_date_

    @property
    def termination_date(self) -> Date:
        return self.termination_date_

    @property
    def term_or_termination_date(self) -> TermOrDate:
        return self.term_or_termination_date_

    @property
    def pay_offset(self) -> Period:
        return self.pay_offset_

    @property
    def fixed_rate(self) -> float:
        return self.fixed_rate_

    @property
    def spread(self) -> float:
        return self.spread_

    @property
    def on_index(self) -> ql.QuantLib.OvernightIndex:
        return self.on_index_

    @property
    def pay_or_rec(self) -> PayOrReceive:
        return self.pay_or_rec_

    @property
    def compounding_method(self) -> CompoundingMethod:
        return self.compounding_method_

    @property
    def accrual_period(self) -> Period:
        return self.accrual_period_

    @property
    def floating_leg_accrual_period(self) -> Period:
        return self.floating_leg_accrual_period_

    @property
    def accrual_basis(self) -> AccrualBasis:
        return self.accrual_basis_

    @property
    def pay_business_day_convention(self) -> BusinessDayConvention:
        return self.pay_business_day_convention_

    @property
    def pay_holiday_convention(self) -> HolidayConvention:
        return self.pay_holiday_convention_

    @property
    def floating_leg(self) -> InterestRateStream:
        return self.floating_leg_

    @property
    def fixed_leg(self) -> InterestRateStream:
        return self.fixed_leg_

    def accept(self, visitor: ProductVisitor):
        return visitor.visit(self)

    def serialize(self) -> dict:
        content = {}
        content["VERSION"] = self._version
        content["TYPE"] = self._product_type
        content["EFFECTIVE_DATE"] = self.effective_date.ISO()
        if self.term_or_termination_date.is_term():
            content["TERM_OR_TERMINATION_DATE"] = self.term_or_termination_date.get_term().__str__()
        else:
            content["TERM_OR_TERMINATION_DATE"] = self.term_or_termination_date.get_date().ISO()
        content["PAYMENT_OFFSET"] = self.pay_offset.__str__()
        content["ON_INDEX"] = self.on_index_str_
        content["FIXED_RATE"] = self.fixed_rate
        content["PAY_OR_REC"] = self.pay_or_rec.to_string().upper()
        content["NOTIONAL"] = self.notional
        content["ACCRUAL_PERIOD"] = self.accrual_period.__str__()
        content["FLOATING_LEG_ACCRUAL_PERIOD"] = self.floating_leg_accrual_period.__str__()
        content["ACCRUAL_BASIS"] = self.accrual_basis.value_str
        content["PAY_BUSINESS_DAY_CONVENTION"] = self.pay_business_day_convention.value_str
        content["PAY_HOLIDAY_CONVENTION"] = self.pay_holiday_convention_.value_str
        content["SPREAD"] = self.spread
        content["COMPOUNDING_METHOD"] = self.compounding_method.to_string().upper()
        return content

    @classmethod
    def deserialize(cls, input_dict) -> 'ProductRFRSwap':
        effective_date = Date(input_dict["EFFECTIVE_DATE"])
        term_or_termination_date = TermOrDate(input_dict["TERM_OR_TERMINATION_DATE"])
        pay_offset = Period(input_dict["PAYMENT_OFFSET"])
        on_index = input_dict["ON_INDEX"]
        fixed_rate = input_dict["FIXED_RATE"]
        pay_or_rec = PayOrReceive.from_string(input_dict["PAY_OR_REC"])
        notional = input_dict["NOTIONAL"]
        accrual_period = Period(input_dict["ACCRUAL_PERIOD"])
        floating_leg_accrual_period = Period(input_dict["FLOATING_LEG_ACCRUAL_PERIOD"])
        accrual_basis = AccrualBasis(input_dict["ACCRUAL_BASIS"])
        pay_business_day_convention = BusinessDayConvention(
            input_dict["PAY_BUSINESS_DAY_CONVENTION"]
        )
        pay_holiday_convention = HolidayConvention(input_dict["PAY_HOLIDAY_CONVENTION"])
        spread = input_dict["SPREAD"]
        compounding_method = CompoundingMethod.from_string(input_dict["COMPOUNDING_METHOD"])
        return cls(
            effective_date,
            term_or_termination_date,
            pay_offset,
            on_index,
            fixed_rate,
            pay_or_rec,
            notional,
            accrual_period,
            accrual_basis,
            floating_leg_accrual_period,
            pay_business_day_convention,
            pay_holiday_convention,
            spread,
            compounding_method,
        )


# Adapted from the instructor template.
class ProductOvernightIndexBasisSwap(Product):

    _version = 1
    _product_type = "PRODUCT_OVERNIGHT_INDEX_BASIS_SWAP"

    def __init__(
        self,
        effective_date: Date,
        term_or_termination_date: TermOrDate,
        payment_off_set: Period,
        on_index_1: str,
        on_index_2: str,
        spread_over_leg_1: float,
        pay_or_rec_leg_1: PayOrReceive,
        notional: float,
        accrual_period_1: Period,
        accrual_basis: AccrualBasis,
        accrual_period_2: Optional[Period] = None,
        pay_business_day_convention: Optional[BusinessDayConvention] = BusinessDayConvention("F"),
        pay_holiday_convention: Optional[HolidayConvention] = HolidayConvention("USGS"),
        compounding_method: Optional[CompoundingMethod] = CompoundingMethod.COMPOUND,
    ) -> None:

        super().__init__()
        effective_date = move_to_business_day(Date(effective_date), pay_business_day_convention, pay_holiday_convention)

        self.on_index_str_1_ = on_index_1
        self.on_index_str_2_ = on_index_2
        self.on_index_1_: ql.QuantLib.OvernightIndex = IndexRegistry().get(self.on_index_str_1_)
        self.on_index_2_: ql.QuantLib.OvernightIndex = IndexRegistry().get(self.on_index_str_2_)
        self.pay_business_day_convention_ = pay_business_day_convention
        self.pay_holiday_convention_ = pay_holiday_convention
        self.first_date_ = self.effective_date_ = effective_date
        self.term_or_termination_date_ = term_or_termination_date
        self.termination_date_ = self.term_or_termination_date_.get_date()
        if self.term_or_termination_date_.is_term():
            calendar: ql.Calendar = self.on_index_1_.fixingCalendar()
            self.termination_date_ = Date(
                calendar.advance(
                    self.effective_date_,
                    self.term_or_termination_date_.get_term(),
                    self.on_index_1_.businessDayConvention(),
                )
            )

        # other attributes
        self.currency_ = Currency(self.on_index_1_.currency().code())
        self.spread_ = spread_over_leg_1
        self.notional_ = notional
        self.pay_or_rec_ = pay_or_rec_leg_1
        self.long_or_short_ = LongOrShort.LONG if notional >= 0 else LongOrShort.SHORT
        self.pay_offset_ = payment_off_set
        self.accrual_basis_ = accrual_basis
        self.accrual_period_1_ = accrual_period_1
        self.accrual_period_2_ = accrual_period_1 if accrual_period_2 is None else accrual_period_2
        self.compounding_method_ = compounding_method

        self.floating_leg_1_basis_ = None
        self.floating_leg_1_wo_basis_ = None
        #TODO
        common = dict(
            effective_date=self.effective_date_,
            termination_date=self.termination_date_,
            notional=self.notional_,
            currency=self.currency_,
            accrual_basis=self.accrual_basis_,
            business_day_convention=self.pay_business_day_convention_,
            holiday_convention=self.pay_holiday_convention_,
            payment_offset=self.pay_offset_,
            payment_business_day_convention=self.pay_business_day_convention_,
            payment_holiday_convention=self.pay_holiday_convention_,
            is_on_index=True,
            ois_compounding=self.compounding_method_,
        )

        self.floating_leg_1_ = InterestRateStream(
            **common,
            accrual_period=self.accrual_period_1_,
            float_index=self.on_index_str_1_,
            ois_spread=self.spread_,
        )

        self.floating_leg_2_ = InterestRateStream(
            **common,
            accrual_period=self.accrual_period_2_,
            float_index=self.on_index_str_2_,
            ois_spread=0.0,
        )

        last_dt_floating_1 = self.floating_leg_1_.last_date
        last_dt_floating_2 = self.floating_leg_2_.last_date
        self.last_date_ = (
            last_dt_floating_2 if last_dt_floating_2 >= last_dt_floating_1 else last_dt_floating_1
        )

    def floating_leg_1_cash_flow(self, i: int) -> Product:
        return self.floating_leg_1_.element(i)

    def floating_leg_2_cash_flow(self, i: int) -> Product:
        return self.floating_leg_2_.element(i)

    @property
    def effective_date(self) -> Date:
        return self.effective_date_

    @property
    def termination_date(self) -> Date:
        return self.termination_date_

    @property
    def term_or_termination_date(self) -> TermOrDate:
        return self.term_or_termination_date_

    @property
    def pay_offset(self) -> Period:
        return self.pay_offset_

    @property
    def spread(self) -> float:
        return self.spread_

    @property
    def on_index_1(self) -> ql.QuantLib.OvernightIndex:
        return self.on_index_1_

    @property
    def on_index_2(self) -> ql.QuantLib.OvernightIndex:
        return self.on_index_2_

    @property
    def pay_or_rec(self) -> PayOrReceive:
        return self.pay_or_rec_

    @property
    def compounding_method(self) -> CompoundingMethod:
        return self.compounding_method_

    @property
    def accrual_period_leg_1(self) -> Period:
        return self.accrual_period_1_

    @property
    def accrual_period_leg_2(self) -> Period:
        return self.accrual_period_2_

    @property
    def accrual_basis(self) -> AccrualBasis:
        return self.accrual_basis_

    @property
    def pay_business_day_convention(self) -> BusinessDayConvention:
        return self.pay_business_day_convention_

    @property
    def pay_holiday_convention(self) -> HolidayConvention:
        return self.pay_holiday_convention_

    @property
    def floating_leg_1(self) -> InterestRateStream:
        return self.floating_leg_1_

    @property
    def floating_leg_2(self) -> InterestRateStream:
        return self.floating_leg_2_

    @property
    def floating_leg_1_basis(self) -> InterestRateStream:
        if self.floating_leg_1_basis_ is None:
            self.floating_leg_1_basis_ = InterestRateStream(
                effective_date=self.effective_date_,
                termination_date=self.termination_date_,
                accrual_period=self.accrual_period_1_,
                notional=self.notional_,
                currency=self.currency_,
                accrual_basis=AccrualBasis(self.on_index_1_.dayCounter().name()),
                business_day_convention=self.pay_business_day_convention_,
                holiday_convention=HolidayConvention(self.on_index_1_.fixingCalendar().name()),
                fixed_rate=self.spread_,
                is_on_index=False,
                payment_offset=self.pay_offset_,
                payment_business_day_convention=self.pay_business_day_convention_,
                payment_holiday_convention=self.pay_holiday_convention_,
            )
        return self.floating_leg_1_basis_

    @property
    def floating_leg_1_wo_basis(self) -> InterestRateStream:
        if self.floating_leg_1_wo_basis_ is None:
            self.floating_leg_1_wo_basis_ = InterestRateStream(
                effective_date=self.effective_date_,
                termination_date=self.termination_date_,
                accrual_period=self.accrual_period_1_,
                notional=self.notional_,
                currency=self.currency_,
                accrual_basis=self.accrual_basis_,
                business_day_convention=self.pay_business_day_convention_,  # Template uses the payment BDC for the accrual schedule.
                holiday_convention=HolidayConvention(self.on_index_1_.fixingCalendar().name()),
                float_index=self.on_index_str_1_,
                ois_compounding=self.compounding_method_,
                ois_spread=0.0,
                fixing_in_arrear=True,
                payment_offset=self.pay_offset_,
                payment_business_day_convention=self.pay_business_day_convention_,
                payment_holiday_convention=self.pay_holiday_convention_,
            )
        return self.floating_leg_1_wo_basis_

    def accept(self, visitor: ProductVisitor):
        return visitor.visit(self)

    def serialize(self) -> dict:
        content = {}
        content["VERSION"] = self._version
        content["TYPE"] = self._product_type
        content["EFFECTIVE_DATE"] = self.effective_date.ISO()
        if self.term_or_termination_date.is_term():
            content["TERM_OR_TERMINATION_DATE"] = self.term_or_termination_date.get_term().__str__()
        else:
            content["TERM_OR_TERMINATION_DATE"] = self.term_or_termination_date.get_date().ISO()
        content["PAYMENT_OFFSET"] = self.pay_offset.__str__()
        content["ON_INDEX_LEG_1"] = self.on_index_str_1_
        content["ON_INDEX_LEG_2"] = self.on_index_str_2_
        content["SPREAD_OVER_LEG_1"] = self.spread
        content["PAY_OR_REC_LEG_1"] = self.pay_or_rec.to_string().upper()
        content["NOTIONAL"] = self.notional
        content["ACCRUAL_PERIOD_1"] = self.accrual_period_leg_1.__str__()
        content["ACCRUAL_PERIOD_2"] = self.accrual_period_leg_2.__str__()
        content["ACCRUAL_BASIS"] = self.accrual_basis.value_str
        content["PAY_BUSINESS_DAY_CONVENTION"] = self.pay_business_day_convention.value_str
        content["PAY_HOLIDAY_CONVENTION"] = self.pay_holiday_convention_.value_str
        content["COMPOUNDING_METHOD"] = self.compounding_method.to_string().upper()
        return content

    @classmethod
    def deserialize(cls, input_dict) -> 'ProductOvernightIndexBasisSwap':
        effective_date = Date(input_dict["EFFECTIVE_DATE"])
        term_or_termination_date = TermOrDate(input_dict["TERM_OR_TERMINATION_DATE"])
        pay_offset = Period(input_dict["PAYMENT_OFFSET"])
        on_index_1 = input_dict["ON_INDEX_LEG_1"]
        on_index_2 = input_dict["ON_INDEX_LEG_2"]
        spread_over_leg_1 = input_dict["SPREAD_OVER_LEG_1"]
        pay_or_rec_leg_1 = PayOrReceive.from_string(input_dict["PAY_OR_REC_LEG_1"])
        notional = input_dict["NOTIONAL"]
        leg_1_accrual_period = Period(input_dict["ACCRUAL_PERIOD_1"])
        leg_2_accrual_period = Period(input_dict["ACCRUAL_PERIOD_2"])
        accrual_basis = AccrualBasis(input_dict["ACCRUAL_BASIS"])
        pay_business_day_convention = BusinessDayConvention(
            input_dict["PAY_BUSINESS_DAY_CONVENTION"]
        )
        pay_holiday_convention = HolidayConvention(input_dict["PAY_HOLIDAY_CONVENTION"])
        compounding_method = CompoundingMethod.from_string(input_dict["COMPOUNDING_METHOD"])

        return cls(
            effective_date,
            term_or_termination_date,
            pay_offset,
            on_index_1,
            on_index_2,
            spread_over_leg_1,
            pay_or_rec_leg_1,
            notional,
            leg_1_accrual_period,
            accrual_basis,
            leg_2_accrual_period,
            pay_business_day_convention,
            pay_holiday_convention,
            compounding_method,
        )


__all__ += ["ProductForwardRateCashflow", "ProductInterestRateStream", "InterestRateStream",
            "ProductFRA", "ProductRFRSwap", "ProductOvernightIndexBasisSwap"]

for _product in (ProductFixedAccruedCashflow, ProductOvernightIndexCashflow,
                 ProductForwardRateCashflow, ProductInterestRateStream, ProductFRA,
                 ProductRFRSwap, ProductOvernightIndexBasisSwap):
    ProductBuilderRegistry().register(_product._product_type + "_DES", _product.deserialize)
