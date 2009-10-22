# -*- encoding: utf-8 -*-
#########################################################################
#                                                                       #
#########################################################################
#                                                                       #
# Copyright (C) 2009  Raphaël Valyi                                     #
#                                                                       #
#This program is free software: you can redistribute it and/or modify   #
#it under the terms of the GNU General Public License as published by   #
#the Free Software Foundation, either version 3 of the License, or      #
#(at your option) any later version.                                    #
#                                                                       #
#This program is distributed in the hope that it will be useful,        #
#but WITHOUT ANY WARRANTY; without even the implied warranty of         #
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          #
#GNU General Public License for more details.                           #
#                                                                       #
#You should have received a copy of the GNU General Public License      #
#along with this program.  If not, see <http://www.gnu.org/licenses/>.  #
#########################################################################

from osv import osv, fields
import magerp_osv
#from base_external_referentials import external_osv

DEBUG = True

class sale_shop(magerp_osv.magerp_osv):
    _inherit = "sale.shop"
    
    def _shop_group_get(self, cr, uid, ids, prop, unknow_none, context):
        res = {}
        for shop in self.browse(cr, uid, ids, context):
            if shop.website_id:
                rid = self.pool.get('external.shop.group').extid_to_oeid(cr, uid, shop.website_id, shop.referential_id.id)
                res[shop.id] = rid
            else:
                res[shop.id] = False
        return res
  
    def _get_rootcategory(self, cr, uid, ids, prop, unknow_none, context):
        res = {}
        for shop in self.browse(cr, uid, ids, context):
            if shop.website_id:
                rid = self.pool.get('product.category').extid_to_oeid(cr, uid, shop.root_category_id, shop.referential_id.id)
                res[shop.id] = rid
            else:
                res[shop.id] = False
        return res

    _columns = {
        'default_store_id':fields.integer('Magento Store ID'), #Many 2 one ?
        'website_id':fields.integer('Magento Website ID'), # Many 2 one ?
        'group_id':fields.integer('Magento ID'),
        'root_category_id':fields.integer('Root product Category'),
        'root_category':fields.function(_get_rootcategory, type="many2one", relation="product.category", method=True, string="Root Category"),
    }
    
    _defaults = {
        'payment_default_id': lambda *a: 1, #required field that would cause trouble if not set when importing
    }


    def export_products_collection(self, cr, uid, shop, exportable_products, ext_connection, ctx):
        #TODO use new API!
        self.pool.get('product.product').mage_export(cr, uid, [product.id for product in exportable_products], ext_connection, shop.referential_id.id, DEBUG)


    def _get_pricelist(self, cr, uid, shop):
        if shop.pricelist_id:
            return shop.pricelist_id.id
        else:
            return self.pool.get('product.pricelist').search(cr, uid, [('type', '=', 'sale'), ('active', '=', True)])[0]
        

    def import_shop_orders(self, cr, uid, shop, ext_connection, ctx):#FIXME: no guest order support for now: [{'customer_id': {'nlike':False}}]
        result = self.pool.get('sale.order').mage_import_base(cr, uid, ext_connection, shop.referential_id.id, defaults={'pricelist_id':self._get_pricelist(cr, uid, shop)}, context={'one_by_one': True, 'ids_or_filter':[{'customer_id': {'nlike':False}}]})
        return result
        #TODO store filter: sock.call(s,'sales_order.list',[{'order_id':{'gt':0},'store_id':{'eq':1}}])
    
sale_shop()


class sale_order_line(magerp_osv.magerp_osv):
    _inherit = "sale.order.line"

sale_order_line()


class sale_order(magerp_osv.magerp_osv):
    _inherit = "sale.order"
    
    _columns = {
        'magento_billing_address_id':fields.integer('Magento Billing Address ID'),
        'magento_shipping_address_id':fields.integer('Magento Billing Address ID'),
        'magento_customer_id':fields.integer('Magento Customer ID'),
    }
    
    def oevals_from_extdata(self, cr, uid, external_referential_id, data_record, key_field, mapping_lines, defaults, context):
        if data_record.get('billing_address', False):
            del(data_record['billing_address']['parent_id'])
            del(data_record['shipping_address']['parent_id'])
        res = super(magerp_osv.magerp_osv, self).oevals_from_extdata(cr, uid, external_referential_id, data_record, key_field, mapping_lines, defaults, context)

        if data_record.get('billing_address', False):
            address_default = {}
            if res.get('parter_id', False):
                address_default = {'parter_id': res.get('parter_id', False)}

            #TODO unlike Magento, avoid creating same addresses over and over, try to detect if customer already have such an address (Magento won't tell it!)
            inv_res = self.pool.get('res.partner.address').ext_import(cr, uid, [data_record['billing_address']], external_referential_id, address_default, context)
            ship_res = self.pool.get('res.partner.address').ext_import(cr, uid, [data_record['shipping_address']], external_referential_id, address_default, context)
            res['partner_order_id'] = len(inv_res['create_ids']) > 0 and inv_res['create_ids'][0] or inv_res['write_ids'][0]
            res['partner_invoice_id'] = res['partner_order_id']
            res['partner_shipping_id'] = (len(ship_res['create_ids']) > 0 and ship_res['create_ids'][0]) or (len(ship_res['write_ids']) > 0 and ship_res['write_ids'][0]) or res['partner_order_id'] #shipping might be the same as invoice address
            

        if data_record.get('items', False):
            mapping_id = self.pool.get('external.mapping').search(cr,uid,[('model','=','sale.order.line'),('referential_id','=',external_referential_id)])
            if mapping_id:
                mapping_line_ids = self.pool.get('external.mapping.line').search(cr,uid,[('mapping_id','=',mapping_id),('type','in',['in_out','in'])])
                mapping_lines = self.pool.get('external.mapping.line').read(cr,uid,mapping_line_ids,['external_field','external_type','in_function'])
                if mapping_lines:
                    lines_vals = []
                    for line_data in data_record.get('items', []):
                        lines_vals.append((0, 0, self.oevals_from_extdata(cr, uid, external_referential_id, line_data, 'item_id', mapping_lines, {'product_uom':1}, context)))
                        
                    if data_record.get('shipping_amount', False) and data_record.get('shipping_amount', False) > 0:
                        ship_product_ids = self.pool.get('product.product').search(cr, uid, [('default_code', '=', 'SHIP MAGENTO')])
                        ship_product = self.pool.get('product.product').browse(cr, uid, ship_product_ids[0], context)
                        lines_vals.append((0, 0, {
                                                    'product_id': ship_product.id,
                                                    'name': ship_product.name,
                                                    'product_uom': ship_product.uom_id.id,
                                                    'product_uom_qty': 1,
                                                    'price_unit': float(data_record['shipping_amount']),
                                                }))
                    res['order_line'] = lines_vals
                
        return res

sale_order()