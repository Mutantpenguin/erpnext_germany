# Copyright (c) 2023, ALYF GmbH and contributors
# For license information, please see license.txt

from datetime import date
from calendar import monthrange
from babel.dates import format_date

import frappe
from frappe import _
from frappe.query_builder.functions import Sum, Cast, Coalesce
from pypika.terms import Case


def execute(filters=None):
	fy_start, month_start, month_end = get_dates(
		int(filters.month), filters.fiscal_year
	)
	current_month_name = format_date(
		month_start, format="MMMM", locale=frappe.local.lang
	)
	return get_columns(current_month_name), get_data(
		filters.company, fy_start, month_start, month_end
	)


def get_columns(current_month_name: str):
	return [
		{
			"fieldname": "account",
			"label": _("Account"),
			"fieldtype": "Link",
			"options": "Account",
			"width": 400,
		},
		{
			"fieldname": "account_currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"width": 100,
		},
		{
			"fieldname": "debit_opening_balance",
			"label": _("Debit Opening Balance"),
			"fieldtype": "Currency",
			"width": 170,
			"options": "account_currency",
		},
		{
			"fieldname": "credit_opening_balance",
			"label": _("Credit Opening Balance"),
			"fieldtype": "Currency",
			"width": 170,
			"options": "account_currency",
		},
		{
			"fieldname": "debit_until_evaluation_period",
			"label": _("Debit until {0}").format(current_month_name),
			"fieldtype": "Currency",
			"width": 170,
			"options": "account_currency",
		},
		{
			"fieldname": "credit_until_evaluation_period",
			"label": _("Credit until {0}").format(current_month_name),
			"fieldtype": "Currency",
			"width": 170,
			"options": "account_currency",
		},
		{
			"fieldname": "debit_in_evaluation_period",
			"label": _("Debit in {0}").format(current_month_name),
			"fieldtype": "Currency",
			"width": 170,
			"options": "account_currency",
		},
		{
			"fieldname": "credit_in_evaluation_period",
			"label": _("Credit in {0}").format(current_month_name),
			"fieldtype": "Currency",
			"width": 170,
			"options": "account_currency",
		},
		{
			"fieldname": "debit_closing_balance",
			"label": _("Debit Closing Balance"),
			"fieldtype": "Currency",
			"width": 170,
			"options": "account_currency",
		},
		{
			"fieldname": "credit_closing_balance",
			"label": _("Credit Closing Balance"),
			"fieldtype": "Currency",
			"width": 170,
			"options": "account_currency",
		},
	]


def get_data(company: str, fy_start, month_start, month_end):
	gl_entry = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")

	opening_balance = (
		frappe.qb.from_(gl_entry)
		.left_join(account)
		.on(gl_entry.account == account.name)
		.select(
			gl_entry.account,
			Case()
			.when(
				account.root_type == "Asset",
				Sum(gl_entry.debit_in_account_currency)
				- Sum(gl_entry.credit_in_account_currency),
			)
			.else_(None)
			.as_("debit"),
			Case()
			.when(
				account.root_type.isin(("Liability", "Equity")),
				Sum(gl_entry.credit_in_account_currency)
				- Sum(gl_entry.debit_in_account_currency),
			)
			.else_(None)
			.as_("credit"),
		)
		.where(
			(gl_entry.company == company)
			& (gl_entry.is_cancelled == 0)
			& (gl_entry.posting_date < fy_start)
		)
		.groupby(gl_entry.account)
	)

	sum_until_month = (
		frappe.qb.from_(gl_entry)
		.select(
			gl_entry.account,
			Sum(gl_entry.debit_in_account_currency).as_("debit"),
			Sum(gl_entry.credit_in_account_currency).as_("credit"),
		)
		.where(
			(gl_entry.company == company)
			& (gl_entry.is_cancelled == 0)
			& (gl_entry.posting_date >= fy_start)
			& (gl_entry.posting_date < month_start)
			& (gl_entry.voucher_type != "Period Closing Voucher")
		)
		.groupby(gl_entry.account)
	)

	sum_in_month = (
		frappe.qb.from_(gl_entry)
		.left_join(account)
		.on(gl_entry.account == account.name)
		.select(
			gl_entry.account,
			gl_entry.account_currency,
			Sum(gl_entry.debit_in_account_currency).as_("debit"),
			Sum(gl_entry.credit_in_account_currency).as_("credit"),
		)
		.where(
			(gl_entry.company == company)
			& (gl_entry.is_cancelled == 0)
			& (gl_entry.posting_date >= month_start)
			& (gl_entry.posting_date <= month_end)
			& (gl_entry.voucher_type != "Period Closing Voucher")
		)
		.orderby(Cast(account.account_number, "int"))
		.groupby(gl_entry.account, gl_entry.account_currency)
	)

	query = (
		frappe.qb.from_(sum_in_month)
		.left_join(sum_until_month)
		.on(sum_until_month.account == sum_in_month.account)
		.left_join(opening_balance)
		.on(opening_balance.account == sum_in_month.account)
		.left_join(account)
		.on(sum_in_month.account == account.name)
		.select(
			sum_in_month.account,
			sum_in_month.account_currency,
			opening_balance.debit,
			opening_balance.credit,
			sum_until_month.debit,
			sum_until_month.credit,
			sum_in_month.debit,
			sum_in_month.credit,
			Case()
			.when(
				account.root_type.isin(("Asset", "Expense")),
				(
					Coalesce(opening_balance.debit, 0)
					+ Coalesce(sum_until_month.debit, 0)
					+ Coalesce(sum_in_month.debit, 0)
				)
				- (
					Coalesce(opening_balance.credit, 0)
					+ Coalesce(sum_until_month.credit, 0)
					+ Coalesce(sum_in_month.credit, 0)
				),
			)
			.else_(None),
			Case()
			.when(
				account.root_type.isin(("Liability", "Equity", "Income")),
				(
					Coalesce(opening_balance.credit, 0)
					+ Coalesce(sum_until_month.credit, 0)
					+ Coalesce(sum_in_month.credit, 0)
				)
				- (
					Coalesce(opening_balance.debit, 0)
					+ Coalesce(sum_until_month.debit, 0)
					+ Coalesce(sum_in_month.debit, 0)
				),
			)
			.else_(None),
		)
	)

	return query.run()


def get_dates(month: int, fiscal_year: str):
	"""Returns the start and end date for the given month."""
	fy_start: date = frappe.db.get_value("Fiscal Year", fiscal_year, "year_start_date")
	month_start = fy_start.replace(month=month, day=1)
	last_day_of_month = monthrange(month_start.year, month_start.month)[1]
	month_end = month_start.replace(day=last_day_of_month)
	return fy_start, month_start, month_end
