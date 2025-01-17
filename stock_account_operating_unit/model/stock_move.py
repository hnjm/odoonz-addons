# © 2019 Eficent Business and IT Consulting Services S.L.
# - Jordi Ballester Alomar
# © 2019 Serpent Consulting Services Pvt. Ltd. - Sudhir Arya
# © 2021 O4SB Ltd - Graeme Gellatly
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).
from odoo import _, exceptions, models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _prepare_common_svl_vals(self,):
        res = super(StockMove, self)._prepare_common_svl_vals()
        if self._is_in():
            res.update({"operating_unit_id": self.operating_unit_dest_id.id})
        if self._is_out():
            res.update({"operating_unit_id": self.operating_unit_id.id})
        if self._is_dropshipped() or self._is_dropshipped_returned():
            res.update({"operating_unit_id": self.picking_id.operating_unit_id.id})
        return res

    def _generate_valuation_lines_data(
        self,
        partner_id,
        qty,
        debit_value,
        credit_value,
        debit_account_id,
        credit_account_id,
        description,
    ):
        rslt = super(StockMove, self)._generate_valuation_lines_data(
            partner_id,
            qty,
            debit_value,
            credit_value,
            debit_account_id,
            credit_account_id,
            description,
        )
        if rslt:
            debit_line_vals = rslt.get("debit_line_vals")
            credit_line_vals = rslt.get("credit_line_vals")
            price_diff_line_vals = rslt.get("price_diff_line_vals", {})

            if (
                self.operating_unit_id
                and self.operating_unit_dest_id
                and self.operating_unit_id != self.operating_unit_dest_id
                and debit_line_vals["account_id"] != credit_line_vals["account_id"]
            ):
                raise exceptions.UserError(
                    _(
                        "You cannot create stock moves involving separate source"
                        " and destination accounts related to different "
                        "operating units."
                    )
                )

            if not self.operating_unit_dest_id and not self.operating_unit_id:
                ou_id = (
                    self.picking_id.picking_type_id.warehouse_id.operating_unit_id.id
                )
                if not ou_id:
                    # e.g. Dropship
                    ou_id = self.picking_id.operating_unit_id.id
            else:
                ou_id = False

            debit_line_vals["operating_unit_id"] = (
                ou_id or self.operating_unit_dest_id.id or self.operating_unit_id.id
            )
            credit_line_vals["operating_unit_id"] = (
                ou_id or self.operating_unit_id.id or self.operating_unit_dest_id.id
            )
            rslt["credit_line_vals"] = credit_line_vals
            rslt["debit_line_vals"] = debit_line_vals
            if price_diff_line_vals:
                price_diff_line_vals["operating_unit_id"] = (
                    ou_id or self.operating_unit_id.id or self.operating_unit_dest_id.id
                )
                rslt["price_diff_line_vals"] = price_diff_line_vals
        return rslt

    def _action_done(self, cancel_backorder=False):
        """
        Generate accounting moves if the product being moved is subject
        to real_time valuation tracking,
        and the source or destination location are
        a transit location or is outside of the company or the source or
        destination locations belong to different operating units.
        """
        res = super(StockMove, self)._action_done(cancel_backorder)
        for move in self:

            if move.product_id.valuation == "real_time":
                # Inter-operating unit moves do not accept to
                # from/to non-internal location
                if (
                    move.location_id.company_id
                    and move.location_id.company_id == move.location_dest_id.company_id
                    and move.location_id.usage in ["transit", "internal"]
                    and move.location_dest_id.usage in ["transit", "internal"]
                    and move.operating_unit_id != move.operating_unit_dest_id
                ):
                    (
                        journal_id,
                        acc_src,
                        acc_dest,
                        acc_valuation,
                    ) = move._get_accounting_data_for_valuation()

                    move_lines = move._prepare_account_move_line(
                        move.product_qty,
                        move.product_id.standard_price * move.product_qty,
                        acc_valuation,
                        acc_valuation,
                        _("%s - OU Move") % move.product_id.display_name,
                    )
                    am = (
                        self.env["account.move"]
                        .sudo()
                        .with_context(company_id=move.company_id.id)
                        .with_company(move.location_id.company_id.id)
                        .create(
                            {
                                "journal_id": journal_id,
                                "line_ids": move_lines,
                                "company_id": move.company_id.id,
                                "ref": move.picking_id and move.picking_id.name,
                                "stock_move_id": move.id,
                            }
                        )
                    )
                    am.action_post()
            return res
